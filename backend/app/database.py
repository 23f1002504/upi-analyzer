from sqlalchemy import create_engine, Column, String, Float, DateTime, Integer, Boolean, Index
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import os, pathlib

DB_URL = os.getenv("DATABASE_URL", "sqlite:///./data/upi.db")

# Fix Render PostgreSQL URL format (postgres:// → postgresql://)
if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

if "sqlite" in DB_URL:
    engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        DB_URL,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class TransactionDB(Base):
    __tablename__ = "transactions"
    id               = Column(Integer, primary_key=True, autoincrement=True)
    user_id          = Column(String, nullable=True, index=True)
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
    id         = Column(Integer, primary_key=True)
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
    title      = Column(String, nullable=False)
    message    = Column(String, nullable=False)
    status     = Column(String, default="new")
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    if "sqlite" in DB_URL:
        pathlib.Path("./data").mkdir(exist_ok=True)
    from .auth import UserDB  # noqa
    Base.metadata.create_all(bind=engine)
    _migrate()


def _migrate():
    """Safe migration — adds missing columns without data loss."""
    try:
        from sqlalchemy import text, inspect
        with engine.connect() as conn:
            inspector = inspect(engine)

            if inspector.has_table('transactions'):
                existing = [c['name'] for c in inspector.get_columns('transactions')]
                to_add = [
                    ("included",        "BOOLEAN DEFAULT TRUE"),
                    ("custom_category", "VARCHAR"),
                    ("source_file",     "VARCHAR"),
                ]
                for col, defn in to_add:
                    if col not in existing:
                        conn.execute(text(f"ALTER TABLE transactions ADD COLUMN {col} {defn}"))
                        conn.commit()

            if inspector.has_table('users'):
                user_cols = [c['name'] for c in inspector.get_columns('users')]
                for col, defn in [("is_admin","BOOLEAN DEFAULT FALSE"),("last_seen","TIMESTAMP")]:
                    if col not in user_cols:
                        conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {defn}"))
                        conn.commit()
    except Exception as e:
        print(f"Migration note: {e}")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
