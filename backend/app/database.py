import os, pathlib
from datetime import datetime
from sqlalchemy import (create_engine, Column, String, Float, DateTime, Integer,
                        Boolean, Index, text, inspect)
from sqlalchemy.orm import declarative_base, sessionmaker

DB_URL = os.getenv("DATABASE_URL", "sqlite:///./data/upi.db")
if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

IS_SQLITE = DB_URL.startswith("sqlite")
if IS_SQLITE:
    engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DB_URL, pool_size=5, max_overflow=10, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class TransactionDB(Base):
    __tablename__ = "transactions"
    id               = Column(Integer, primary_key=True, autoincrement=True)
    user_id          = Column(Integer, nullable=True, index=True)
    date             = Column(DateTime, nullable=False, index=True)
    time             = Column(String, default="00:00")
    amount           = Column(Float, nullable=False)
    transaction_type = Column(String, nullable=False)
    merchant         = Column(String, nullable=False)
    category         = Column(String, nullable=True)
    custom_category  = Column(String, nullable=True)
    note             = Column(String, default="")
    cashback         = Column(Float, default=0.0)
    source_file      = Column(String, nullable=True)
    included         = Column(Boolean, default=True)
    __table_args__ = (Index("ix_user_date", "user_id", "date"),)


class SiteContent(Base):
    __tablename__ = "site_content"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    key        = Column(String, unique=True, nullable=False)
    value      = Column(String, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(Integer, nullable=True)


class Suggestion(Base):
    __tablename__ = "suggestions"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    user_id    = Column(Integer, nullable=True)
    user_name  = Column(String, nullable=True)
    user_email = Column(String, nullable=True)
    category   = Column(String, default="feature")
    title      = Column(String, nullable=False)
    message    = Column(String, nullable=False)
    status     = Column(String, default="new")
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    if IS_SQLITE:
        pathlib.Path("./data").mkdir(exist_ok=True)
    from . import auth  # noqa: registers UserDB on Base
    Base.metadata.create_all(bind=engine)
    _migrate()


def _migrate():
    """Add columns that older databases are missing. Never drops data."""
    true_lit = "1" if IS_SQLITE else "TRUE"
    false_lit = "0" if IS_SQLITE else "FALSE"
    wanted = {
        "transactions": [("included", f"BOOLEAN DEFAULT {true_lit}"),
                         ("custom_category", "VARCHAR"),
                         ("source_file", "VARCHAR")],
        "users":        [("is_admin", f"BOOLEAN DEFAULT {false_lit}"),
                         ("is_active", f"BOOLEAN DEFAULT {true_lit}"),
                         ("last_seen", "TIMESTAMP"),
                         ("last_activity", "VARCHAR")],
        "suggestions":  [("category", "VARCHAR DEFAULT 'feature'")],
    }
    try:
        insp = inspect(engine)
        with engine.begin() as conn:
            for table, cols in wanted.items():
                if not insp.has_table(table):
                    continue
                have = {c["name"] for c in insp.get_columns(table)}
                for name, ddl in cols:
                    if name not in have:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                        print(f"migrated: {table}.{name}")
            # old Postgres DBs stored transactions.user_id as VARCHAR
            if not IS_SQLITE and insp.has_table("transactions"):
                row = conn.execute(text(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_name='transactions' AND column_name='user_id'")).fetchone()
                if row and "char" in row[0].lower():
                    conn.execute(text("ALTER TABLE transactions ALTER COLUMN user_id "
                                      "TYPE INTEGER USING NULLIF(user_id,'')::INTEGER"))
                    print("migrated: transactions.user_id -> INTEGER")
    except Exception as e:
        print(f"migration warning: {e}")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
