import os
from datetime import datetime
from .auth import UserDB, hash_pw

ADMIN_EMAIL    = os.getenv("ADMIN_EMAIL", "adminabd@gmail.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "adminabd899")
ADMIN_NAME     = os.getenv("ADMIN_NAME", "Admin")


def seed(db):
    """Create the admin once. Never overwrites a password the admin changed,
    unless ADMIN_RESET_PASSWORD=1 is set."""
    u = db.query(UserDB).filter(UserDB.email == ADMIN_EMAIL).first()
    if not u:
        db.add(UserDB(email=ADMIN_EMAIL, name=ADMIN_NAME,
                      hashed_pw=hash_pw(ADMIN_PASSWORD), is_admin=True,
                      is_active=True, created_at=datetime.utcnow()))
        db.commit()
        print(f"admin created: {ADMIN_EMAIL}")
        return
    changed = False
    if not u.is_admin:
        u.is_admin = True; changed = True
    if os.getenv("ADMIN_RESET_PASSWORD") == "1":
        u.hashed_pw = hash_pw(ADMIN_PASSWORD); changed = True
    if changed:
        db.commit()
    print(f"admin ok: {ADMIN_EMAIL}")
