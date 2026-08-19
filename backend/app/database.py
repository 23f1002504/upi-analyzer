from sqlalchemy import create_engine, Column, String, Float, DateTime, Integer, Boolean, Index
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import os, pathlib

DB_URL = os.getenv("DATABASE_URL", "sqlite:///./data/upi.db")

engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DB_URL else {}
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
    """Editable site content — admin can update via dashboard."""
    __tablename__ = "site_content"
    id         = Column(Integer, primary_key=True)
    key        = Column(String, unique=True, nullable=False)  # e.g. "about_title"
    value      = Column(String, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(Integer, nullable=True)  # user id


class Suggestion(Base):
    """User suggestions submitted from About tab."""
    __tablename__ = "suggestions"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    user_id    = Column(Integer, nullable=True)
    user_name  = Column(String, nullable=True)
    user_email = Column(String, nullable=True)
    title      = Column(String, nullable=False)
    message    = Column(String, nullable=False)
    status     = Column(String, default="new")  # new | reviewed | done
    created_at = Column(DateTime, default=datetime.utcnow)

def init_db():
    pathlib.Path("./data").mkdir(exist_ok=True)
    from .auth import UserDB  # noqa
    Base.metadata.create_all(bind=engine)
    _migrate()


def _migrate():
    """Add missing columns to existing DB without data loss."""
    try:
        with engine.connect() as conn:
            from sqlalchemy import text, inspect
            inspector = inspect(engine)
            existing = [c['name'] for c in inspector.get_columns('transactions')]
            to_add = [
                ("included",        "BOOLEAN DEFAULT 1"),
                ("custom_category", "VARCHAR"),
                ("source_file",     "VARCHAR"),
            ]
            for col, defn in to_add:
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE transactions ADD COLUMN {col} {defn}"))
                    conn.commit()
                    print(f"Migrated: added {col}")

            # Add is_admin and last_seen to users if missing
            if inspector.has_table('users'):
                user_cols = [c['name'] for c in inspector.get_columns('users')]
                user_adds = [
                    ("is_admin",  "BOOLEAN DEFAULT 0"),
                    ("last_seen", "DATETIME"),
                ]
                for col, defn in user_adds:
                    if col not in user_cols:
                        conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {defn}"))
                        conn.commit()
                        print(f"Migrated: added users.{col}")
    except Exception as e:
        print(f"Migration note: {e}")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
