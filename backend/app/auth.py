import os, hashlib, hmac, secrets
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, String, DateTime, Boolean
from .database import Base, get_db

SECRET_KEY = os.getenv("SECRET_KEY", "upi-analyzer-secret-change-in-production-xyz123")
ALGORITHM  = "HS256"
TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


class UserDB(Base):
    __tablename__ = "users"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    email      = Column(String, unique=True, nullable=False, index=True)
    name       = Column(String, nullable=False)
    hashed_pw  = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active  = Column(Boolean, default=True)


def hash_pw(pw: str) -> str:
    """SHA-256 + HMAC with SECRET_KEY. Simple, no external deps."""
    return hmac.new(SECRET_KEY.encode(), pw.encode(), hashlib.sha256).hexdigest()

def verify_pw(plain: str, hashed: str) -> bool:
    return hmac.compare_digest(hash_pw(plain), hashed)

def create_token(data: dict) -> str:
    exp = datetime.utcnow() + timedelta(minutes=TOKEN_EXPIRE_MINUTES)
    return jwt.encode({**data, "exp": exp}, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    if not token: return None
    payload = decode_token(token)
    if not payload: return None
    return db.query(UserDB).filter(UserDB.email == payload.get("sub")).first()

def require_user(user = Depends(get_current_user)):
    if not user: raise HTTPException(status_code=401, detail="Not authenticated")
    return user
