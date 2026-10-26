import os, hashlib, hmac
from datetime import datetime

ADMIN_EMAIL    = os.getenv("ADMIN_EMAIL",    "adminabd@gmail.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "adminabd899")
ADMIN_NAME     = os.getenv("ADMIN_NAME",     "Admin")
SECRET_KEY     = os.getenv("SECRET_KEY",     "upi-analyzer-secret-change-in-production-xyz123")

def hash_pw(pw: str) -> str:
    return hmac.new(SECRET_KEY.encode(), pw.encode(), hashlib.sha256).hexdigest()

def seed(db):
    from .auth import UserDB
    existing = db.query(UserDB).filter(UserDB.email == ADMIN_EMAIL).first()
    if not existing:
        admin = UserDB(
            email      = ADMIN_EMAIL,
            name       = ADMIN_NAME,
            hashed_pw  = hash_pw(ADMIN_PASSWORD),
            is_admin   = True,
            is_active  = True,
            created_at = datetime.utcnow(),
        )
        db.add(admin)
        db.commit()
        print(f"✓ Admin created: {ADMIN_EMAIL}")
    else:
        # Always update hash and ensure is_admin=True
        existing.hashed_pw = hash_pw(ADMIN_PASSWORD)
        existing.is_admin  = True
        db.commit()
        print(f"✓ Admin updated: {ADMIN_EMAIL}")
