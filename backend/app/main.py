import io, math
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from .pdf_parser import UPIPDFParser
from .analytics import AnalyticsEngine
from .models import Transaction
from .csv_parsers import parse_any_csv
from .database import init_db, get_db, SessionLocal, TransactionDB, SiteContent, Suggestion
from .auth import (UserDB, hash_pw, verify_pw, create_token,
                   get_current_user, require_user, require_admin)
from . import rag_service

app = FastAPI(title="UPI Transaction Analyzer")

# Registered BEFORE CORS so CORS is the outer layer: even a crash returns a JSON
# 500 *with* CORS headers (otherwise the browser only shows a confusing CORS error).
@app.middleware("http")
async def _catch_all(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        print(f"[500] {request.method} {request.url.path}: {type(e).__name__}: {e}")
        return JSONResponse({"detail": f"Server error: {type(e).__name__}"}, status_code=500)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_pdf = UPIPDFParser()

DEFAULT_CATEGORIES = ['Credit Card', 'Education', 'Entertainment', 'Food & Grocery', 'Healthcare',
                      'Other', 'Shopping', 'Transfer', 'Transport', 'Travel', 'Utilities']

DEFAULT_ABOUT = {
    "about_title": "UPI Transaction Analyzer",
    "about_subtitle": "See where your money really goes — across every month, every app.",
    "about_body": (
        "What is this?\n"
        "A private dashboard that turns your UPI statements into clear answers: how much you spent, "
        "where it went, who paid you, and how it changes month to month.\n\n"
        "What can it do?\n"
        "• Import statements from PhonePe, Google Pay and SuperMoney (CSV or PDF)\n"
        "• Combine uploads from different months — duplicates are skipped automatically\n"
        "• Filter everything by any date range\n"
        "• Charts for categories, merchants, weekdays, income and monthly trends\n"
        "• Re-categorise any transaction or leave it out of the analytics\n"
        "• Ask the AI questions about your own spending\n\n"
        "How to use it\n"
        "1. Create an account and sign in\n"
        "2. Click Import CSV / PDF in the sidebar and pick your statement\n"
        "3. Explore Overview, Analytics and Transactions\n"
        "4. Open AI Chat and ask things like “What did I spend on food in May?”\n"
        "5. Upload newer statements any time — your history stays\n\n"
        "Privacy\n"
        "Your data is stored under your account only. Account numbers, UPI IDs and phone numbers are "
        "masked before anything reaches the AI.\n\n"
        "Built by AM."
    ),
    "about_version": "v2.1",
}
ABOUT_KEYS = set(DEFAULT_ABOUT)


def _seed_about(db: Session):
    for k, v in DEFAULT_ABOUT.items():
        if not db.query(SiteContent).filter(SiteContent.key == k).first():
            db.add(SiteContent(key=k, value=v))
    db.commit()


@app.on_event("startup")
def startup():
    init_db()
    db = SessionLocal()
    try:
        from .seed_admin import seed
        seed(db)
        _seed_about(db)
    except Exception as e:
        print(f"startup seed error: {type(e).__name__}: {e}")
    finally:
        db.close()


# ── helpers ───────────────────────────────────────────────────────────────────
def _safe(o):
    if isinstance(o, dict):  return {k: _safe(v) for k, v in o.items()}
    if isinstance(o, list):  return [_safe(v) for v in o]
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)): return None
    return o

def _row(t: TransactionDB) -> dict:
    custom = t.custom_category
    return {"id": t.id, "date": t.date.isoformat(), "time": t.time, "amount": t.amount,
            "transaction_type": t.transaction_type, "merchant": t.merchant,
            "category": custom or t.category or "Other", "base_category": t.category,
            "custom_category": custom, "note": t.note or "", "cashback": t.cashback or 0.0,
            "included": True if t.included is None else bool(t.included)}

def _parse_day(s: str, end: bool = False) -> datetime:
    s = s.strip()
    if "T" in s:
        return datetime.fromisoformat(s)
    d = datetime.fromisoformat(s)
    return d.replace(hour=23, minute=59, second=59) if end else d

def _query(db: Session, uid: int, date_from=None, date_to=None, all_rows=False) -> List[TransactionDB]:
    q = db.query(TransactionDB).filter(TransactionDB.user_id == uid)   # always scoped to one user
    if date_from: q = q.filter(TransactionDB.date >= _parse_day(date_from))
    if date_to:   q = q.filter(TransactionDB.date <= _parse_day(date_to, end=True))
    if not all_rows:
        q = q.filter((TransactionDB.included == True) | (TransactionDB.included == None))  # noqa: E712
    return q.order_by(TransactionDB.date.desc(), TransactionDB.id.desc()).all()

def _to_models(txns: List[TransactionDB]) -> List[Transaction]:
    return [Transaction(date=t.date, time=t.time or "00:00", amount=t.amount,
                        transaction_type=t.transaction_type, merchant=t.merchant,
                        category=t.custom_category or t.category, note=t.note or "",
                        cashback=t.cashback or 0.0) for t in txns]

def _dedup_insert(db: Session, rows: list, source: str, uid: int):
    """Insert only what the user does not already have.
    Matching is count-based on (date, type, merchant, amount, time): two identical coffees on one
    day are both kept, re-uploading a file adds nothing, and overlapping statements add only the new rows."""
    if not rows:
        return 0, 0
    from collections import Counter
    dts = [datetime.fromisoformat(r["date"]) if isinstance(r["date"], str) else r["date"] for r in rows]
    def key(dt, typ, merchant, amount, tm):
        return (dt, typ, merchant, round(float(amount), 2), tm or "00:00")
    have = Counter(key(t.date, t.transaction_type, t.merchant, t.amount, t.time) for t in
                   db.query(TransactionDB.date, TransactionDB.transaction_type, TransactionDB.merchant,
                            TransactionDB.amount, TransactionDB.time)
                     .filter(TransactionDB.user_id == uid,
                             TransactionDB.date >= min(dts), TransactionDB.date <= max(dts)).all())
    seen, ins, skp = Counter(), 0, 0
    for r, dt in zip(rows, dts):
        k = key(dt, r["transaction_type"], r["merchant"], r["amount"], r.get("time"))
        seen[k] += 1
        if seen[k] <= have[k]:
            skp += 1
            continue
        db.add(TransactionDB(user_id=uid, date=dt, time=r.get("time", "00:00"), amount=float(r["amount"]),
                             transaction_type=r["transaction_type"], merchant=r["merchant"],
                             category=r.get("category") or "Other", note=r.get("note", ""),
                             cashback=r.get("cashback", 0.0), source_file=source))
        ins += 1
    db.commit()
    return ins, skp

def _count(db: Session, uid: int) -> int:
    return db.query(TransactionDB).filter(TransactionDB.user_id == uid).count()

def _user_json(u: UserDB) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "is_admin": bool(u.is_admin)}


# ── auth ──────────────────────────────────────────────────────────────────────
class RegisterReq(BaseModel):
    email: str
    name: str
    password: str

class LoginReq(BaseModel):
    email: str
    password: str

class ChangePwReq(BaseModel):
    current_password: str
    new_password: str

class HeartbeatReq(BaseModel):
    tab: str = ""

@app.post("/api/auth/register")
def register(req: RegisterReq, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    if "@" not in email or len(req.password) < 6 or not req.name.strip():
        raise HTTPException(400, "Enter a name, a valid email and a password of 6+ characters")
    if db.query(UserDB).filter(func.lower(UserDB.email) == email).first():
        raise HTTPException(400, "Email already registered")
    u = UserDB(email=email, name=req.name.strip()[:60], hashed_pw=hash_pw(req.password),
               created_at=datetime.utcnow(), last_seen=datetime.utcnow())
    db.add(u); db.commit(); db.refresh(u)
    return {"token": create_token({"sub": u.email, "uid": u.id}), "user": _user_json(u)}

@app.post("/api/auth/login")
def login(req: LoginReq, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    u = db.query(UserDB).filter(func.lower(UserDB.email) == email).first()
    if not u or not verify_pw(req.password, u.hashed_pw):
        raise HTTPException(401, "Invalid email or password")
    u.last_seen = datetime.utcnow(); u.last_activity = "Signed in"
    db.commit()
    return {"token": create_token({"sub": u.email, "uid": u.id}), "user": _user_json(u)}

@app.get("/api/auth/me")
def me(user: UserDB = Depends(require_user)):
    return _user_json(user)

@app.post("/api/auth/change-password")
def change_password(req: ChangePwReq, db: Session = Depends(get_db), user: UserDB = Depends(require_user)):
    if not verify_pw(req.current_password, user.hashed_pw):
        raise HTTPException(400, "Current password is incorrect")
    if len(req.new_password) < 6:
        raise HTTPException(400, "New password must be at least 6 characters")
    user.hashed_pw = hash_pw(req.new_password)
    db.commit()
    return {"ok": True}

@app.post("/api/auth/logout")
def logout(db: Session = Depends(get_db), user: Optional[UserDB] = Depends(get_current_user)):
    if user:                                   # show as offline in the admin console straight away
        user.last_seen = datetime.utcnow() - timedelta(hours=1)
        user.last_activity = ""
        db.commit()
    return {"ok": True}

@app.post("/api/heartbeat")
def heartbeat(req: HeartbeatReq, db: Session = Depends(get_db), user: UserDB = Depends(require_user)):
    user.last_seen = datetime.utcnow()
    user.last_activity = (req.tab or "")[:40]
    db.commit()
    return {"ok": True}


# ── upload ────────────────────────────────────────────────────────────────────
@app.post("/api/upload")
async def upload_pdf(file: UploadFile = File(...), db: Session = Depends(get_db),
                     user: UserDB = Depends(require_user)):
    try:
        txns = _pdf.parse_pdf(io.BytesIO(await file.read()))
    except Exception as e:
        raise HTTPException(400, f"Could not read this PDF ({type(e).__name__})")
    rows = [{**t.model_dump(), "date": t.date.isoformat()} for t in txns]
    if not rows:
        raise HTTPException(400, "No transactions found in this PDF. Try the CSV export instead.")
    ins, skp = _dedup_insert(db, rows, file.filename, user.id)
    return JSONResponse(_safe({"count": len(rows), "inserted": ins, "skipped": skp,
                               "total_stored": _count(db, user.id), "format": "PDF"}))

@app.post("/api/upload-csv")
async def upload_csv(file: UploadFile = File(...), db: Session = Depends(get_db),
                     user: UserDB = Depends(require_user)):
    content = await file.read()
    rows, fmt = parse_any_csv(content)
    if not rows:
        raise HTTPException(400, "Could not read this file. Supported: PhonePe, Google Pay and SuperMoney exports.")
    ins, skp = _dedup_insert(db, rows, file.filename, user.id)
    return JSONResponse(_safe({"count": len(rows), "inserted": ins, "skipped": skp,
                               "total_stored": _count(db, user.id), "format": fmt}))


# ── data ──────────────────────────────────────────────────────────────────────
@app.get("/api/transactions")
def get_transactions(date_from: str = None, date_to: str = None, db: Session = Depends(get_db),
                     user: UserDB = Depends(require_user)):
    txns = _query(db, user.id, date_from, date_to, all_rows=True)
    return JSONResponse(_safe({"transactions": [_row(t) for t in txns], "count": len(txns)}))

@app.delete("/api/transactions")
def clear_transactions(db: Session = Depends(get_db), user: UserDB = Depends(require_user)):
    db.query(TransactionDB).filter(TransactionDB.user_id == user.id).delete()
    db.commit()
    return {"cleared": True}

@app.get("/api/analytics")
def analytics(date_from: str = None, date_to: str = None, db: Session = Depends(get_db),
              user: UserDB = Depends(require_user)):
    txns = _query(db, user.id, date_from, date_to)
    if not txns:
        raise HTTPException(404, "No transactions in the selected range")
    return JSONResponse(_safe(AnalyticsEngine(_to_models(txns)).get_analytics()))

@app.get("/api/date-range")
def date_range(db: Session = Depends(get_db), user: UserDB = Depends(require_user)):
    lo, hi, n = db.query(func.min(TransactionDB.date), func.max(TransactionDB.date),
                         func.count(TransactionDB.id)).filter(TransactionDB.user_id == user.id).first()
    return {"min": lo.date().isoformat() if lo else None,
            "max": hi.date().isoformat() if hi else None, "count": n or 0}

class UpdateTxnReq(BaseModel):
    included: Optional[bool] = None
    category: Optional[str] = None

def _categories_for(db: Session, uid: int) -> List[str]:
    custom = {r[0] for r in db.query(TransactionDB.custom_category)
              .filter(TransactionDB.user_id == uid, TransactionDB.custom_category.isnot(None)).all() if r[0]}
    return sorted(set(DEFAULT_CATEGORIES) | custom)

@app.patch("/api/transactions/{txn_id}")
def update_transaction(txn_id: int, req: UpdateTxnReq, db: Session = Depends(get_db),
                       user: UserDB = Depends(require_user)):
    t = db.query(TransactionDB).filter(TransactionDB.id == txn_id, TransactionDB.user_id == user.id).first()
    if not t:
        raise HTTPException(404, "Transaction not found")
    if req.included is not None:
        t.included = req.included
    if req.category is not None:
        cat = req.category.strip()[:40]
        if not cat:
            raise HTTPException(400, "Category cannot be empty")
        t.custom_category = None if cat == t.category else cat
    db.commit()
    row = _row(t)
    row["all_categories"] = _categories_for(db, user.id)
    return row

@app.get("/api/categories")
def get_categories(db: Session = Depends(get_db), user: UserDB = Depends(require_user)):
    return {"categories": _categories_for(db, user.id)}


# ── AI / RAG ──────────────────────────────────────────────────────────────────
class RAGReq(BaseModel):
    question: str

def _rag_context(db: Session, uid: int):
    txns = _query(db, uid)
    if not txns:
        return None, None
    stats = AnalyticsEngine(_to_models(txns)).get_analytics()
    dates = [t.date for t in txns]
    stats["date_range"] = f"{min(dates):%d %b %Y} to {max(dates):%d %b %Y}"
    docs = rag_service.build_docs([_row(t) for t in txns])
    return stats, docs

@app.get("/api/rag/status")
def rag_status(user: Optional[UserDB] = Depends(get_current_user)):
    st = rag_service.index_state(str(user.id)) if user else {"status": "none", "count": 0}
    return {"ai": rag_service.ai_status(), "index": st}

@app.post("/api/rag/index")
def rag_index(db: Session = Depends(get_db), user: UserDB = Depends(require_user)):
    stats, docs = _rag_context(db, user.id)
    if not docs:
        return {"indexed": 0, "status": "empty"}
    status = rag_service.ensure_index(str(user.id), docs)
    return {"indexed": len(docs), "status": status}

@app.post("/api/rag/query")
def rag_query(req: RAGReq, db: Session = Depends(get_db), user: UserDB = Depends(require_user)):
    q = req.question.strip()
    if not q:
        raise HTTPException(400, "Ask a question first")
    stats, docs = _rag_context(db, user.id)
    if not docs:
        return {"answer": "You have no transactions yet. Import a statement first.", "sources": [], "provider": "none"}
    try:
        return rag_service.query(q[:500], user.id, stats, docs)
    except Exception as e:
        print(f"[rag] query crashed: {type(e).__name__}: {e}")
        return {"answer": f"The AI hit an unexpected error ({type(e).__name__}). Please try again.",
                "sources": [], "provider": "none", "error": str(e)[:200]}


# ── about + suggestions ───────────────────────────────────────────────────────
@app.get("/api/about")
def get_about(db: Session = Depends(get_db)):
    data = dict(DEFAULT_ABOUT)
    for r in db.query(SiteContent).all():
        if r.key in ABOUT_KEYS:
            data[r.key] = r.value
    return data

@app.put("/api/about")
def update_about(data: dict, db: Session = Depends(get_db), admin: UserDB = Depends(require_admin)):
    for k, v in data.items():
        if k not in ABOUT_KEYS:
            continue
        row = db.query(SiteContent).filter(SiteContent.key == k).first()
        if row:
            row.value, row.updated_at, row.updated_by = str(v)[:6000], datetime.utcnow(), admin.id
        else:
            db.add(SiteContent(key=k, value=str(v)[:6000], updated_by=admin.id))
    db.commit()
    return get_about(db)

class SuggestionReq(BaseModel):
    title: str
    message: str
    category: str = "feature"

@app.post("/api/suggestions")
def submit_suggestion(req: SuggestionReq, db: Session = Depends(get_db),
                      user: Optional[UserDB] = Depends(get_current_user)):
    title, msg = req.title.strip(), req.message.strip()
    if len(title) < 3 or len(msg) < 10:
        raise HTTPException(400, "Please add a short title and a few words of detail")
    since = datetime.utcnow() - timedelta(days=1)
    if user and db.query(Suggestion).filter(Suggestion.user_id == user.id, Suggestion.created_at >= since).count() >= 10:
        raise HTTPException(429, "Daily suggestion limit reached, thank you!")
    cat = req.category if req.category in ("feature", "bug", "design", "other") else "other"
    db.add(Suggestion(user_id=user.id if user else None, user_name=user.name if user else "Anonymous",
                      user_email=user.email if user else None, category=cat,
                      title=title[:120], message=msg[:1500]))
    db.commit()
    return {"ok": True}


# ── admin ─────────────────────────────────────────────────────────────────────
ONLINE_SECONDS = 150   # frontend heartbeats every 30s

def _is_online(u: UserDB, now: datetime) -> bool:
    return bool(u.last_seen and (now - u.last_seen).total_seconds() < ONLINE_SECONDS)

@app.get("/api/admin/stats")
def admin_stats(db: Session = Depends(get_db), admin: UserDB = Depends(require_admin)):
    now = datetime.utcnow()
    return {
        "total_users": db.query(func.count(UserDB.id)).scalar() or 0,
        "online_now": db.query(func.count(UserDB.id)).filter(
            UserDB.last_seen >= now - timedelta(seconds=ONLINE_SECONDS)).scalar() or 0,
        "new_today": db.query(func.count(UserDB.id)).filter(
            UserDB.created_at >= now.replace(hour=0, minute=0, second=0, microsecond=0)).scalar() or 0,
        "total_txns": db.query(func.count(TransactionDB.id)).scalar() or 0,
        "new_suggestions": db.query(func.count(Suggestion.id)).filter(Suggestion.status == "new").scalar() or 0,
    }

@app.get("/api/admin/users")
def admin_users(db: Session = Depends(get_db), admin: UserDB = Depends(require_admin)):
    now = datetime.utcnow()
    counts = dict(db.query(TransactionDB.user_id, func.count(TransactionDB.id)).group_by(TransactionDB.user_id).all())
    latest = dict(db.query(TransactionDB.user_id, func.max(TransactionDB.date)).group_by(TransactionDB.user_id).all())
    sugg = dict(db.query(Suggestion.user_id, func.count(Suggestion.id)).group_by(Suggestion.user_id).all())
    out = []
    for u in db.query(UserDB).all():
        online = _is_online(u, now)
        out.append({"id": u.id, "name": u.name, "email": u.email, "is_admin": bool(u.is_admin),
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                    "last_seen": u.last_seen.isoformat() if u.last_seen else None,
                    "online": online, "activity": (u.last_activity or "") if online else "",
                    "txn_count": counts.get(u.id, 0),
                    "latest_txn_date": latest[u.id].isoformat() if latest.get(u.id) else None,
                    "suggestions": sugg.get(u.id, 0)})
    out.sort(key=lambda x: (x["online"], x["last_seen"] or ""), reverse=True)
    return {"users": out, "total": len(out), "online_now": sum(1 for x in out if x["online"])}

class RoleReq(BaseModel):
    is_admin: bool

@app.patch("/api/admin/users/{user_id}")
def admin_set_role(user_id: int, req: RoleReq, db: Session = Depends(get_db), admin: UserDB = Depends(require_admin)):
    u = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not u: raise HTTPException(404, "User not found")
    if u.id == admin.id and not req.is_admin: raise HTTPException(400, "You cannot remove your own admin role")
    u.is_admin = req.is_admin
    db.commit()
    return {"ok": True}

@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: int, db: Session = Depends(get_db), admin: UserDB = Depends(require_admin)):
    u = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not u: raise HTTPException(404, "User not found")
    if u.id == admin.id: raise HTTPException(400, "You cannot delete yourself")
    db.query(TransactionDB).filter(TransactionDB.user_id == u.id).delete()
    db.delete(u)
    db.commit()
    return {"ok": True}

@app.get("/api/admin/suggestions")
def admin_suggestions(db: Session = Depends(get_db), admin: UserDB = Depends(require_admin)):
    rows = db.query(Suggestion).order_by(Suggestion.created_at.desc()).all()
    return {"suggestions": [{"id": r.id, "user_id": r.user_id, "user_name": r.user_name,
                             "user_email": r.user_email, "category": r.category or "other",
                             "title": r.title, "message": r.message, "status": r.status,
                             "created_at": r.created_at.isoformat()} for r in rows]}

class StatusReq(BaseModel):
    status: str

@app.patch("/api/admin/suggestions/{sid}")
def admin_update_suggestion(sid: int, req: StatusReq, db: Session = Depends(get_db), admin: UserDB = Depends(require_admin)):
    s = db.query(Suggestion).filter(Suggestion.id == sid).first()
    if not s: raise HTTPException(404, "Not found")
    if req.status not in ("new", "reviewed", "done"): raise HTTPException(400, "Bad status")
    s.status = req.status
    db.commit()
    return {"ok": True}

@app.delete("/api/admin/suggestions/{sid}")
def admin_delete_suggestion(sid: int, db: Session = Depends(get_db), admin: UserDB = Depends(require_admin)):
    s = db.query(Suggestion).filter(Suggestion.id == sid).first()
    if s:
        db.delete(s); db.commit()
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.get("/")
def root():
    return {"service": "UPI Analyzer API", "status": "ok"}
