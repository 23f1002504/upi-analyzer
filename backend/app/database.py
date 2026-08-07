from sqlalchemy import create_engine, Column, String, Float, DateTime, Integer, Boolean, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os

DB_URL = os.getenv("DATABASE_URL", "sqlite:///./data/upi.db")

# For PostgreSQL later: "postgresql://user:pass@host/dbname"
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
     # ready for auth
    date             = Column(DateTime, nullable=False, index=True)
    time             = Column(String, default="00:00")
    amount           = Column(Float, nullable=False)
    transaction_type = Column(String, nullable=False)  # sent | received
    merchant         = Column(String, nullable=False)
    category         = Column(String, nullable=True)
    note             = Column(String, default="")
    cashback         = Column(Float, default=0.0)
    source_file      = Column(String, nullable=True)   # which CSV it came from

    __table_args__ = (
        Index("ix_user_date", "user_id", "date"),
    )


def init_db():
    import pathlib
    pathlib.Path("./data").mkdir(exist_ok=True)
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
