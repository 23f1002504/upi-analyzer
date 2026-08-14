from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Query, Form
from typing import Optional
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
import pandas as pd
import numpy as np
import io, math, re
from datetime import datetime

from .pdf_parser import UPIPDFParser
from .analytics import AnalyticsEngine
from .models import Transaction
from .database import init_db, get_db, TransactionDB
from .auth import (UserDB, hash_pw, verify_pw, create_token,
                   get_current_user, require_user, require_admin)
from . import rag_service

app = FastAPI(title="UPI Transaction Analyzer")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

_parser = UPIPDFParser()

@app.on_event("startup")
def startup():
    init_db()

def _safe(obj):
    if isinstance(obj, dict):  return {k: _safe(v) for k, v in obj.items()}
    if isinstance(obj, list):  return [_safe(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)): return None
    return obj

def _s(x):
    return str(x).strip() if (x is not None and str(x).strip() not in ('nan','None','')) else ''

def _row(t: TransactionDB) -> dict:
    custom_cat = getattr(t, 'custom_category', None)
    included   = getattr(t, 'included', True)
    return {
        "id": t.id, "date": t.date.isoformat(), "time": t.time,
        "amount": t.amount, "transaction_type": t.transaction_type,
        "merchant": t.merchant,
        "category": custom_cat or t.category,
        "base_category": t.category,
        "custom_category": custom_cat,
        "note": t.note, "cashback": t.cashback,
        "included": included if included is not None else True,
    }

def _dedup_insert(db, rows, source, user_id=None):
    inserted = skipped = 0
    for r in rows:
        dt = r.get("date")
        if isinstance(dt, str): dt = datetime.fromisoformat(dt)
        exists = db.query(TransactionDB).filter(
            TransactionDB.date == dt,
            TransactionDB.merchant == r["merchant"],
            TransactionDB.amount == r["amount"],
            TransactionDB.user_id == user_id,
        ).first()
        if exists: skipped += 1; continue
        db.add(TransactionDB(
            user_id=user_id, date=dt, time=r.get("time","00:00"),
            amount=r["amount"], transaction_type=r["transaction_type"],
            merchant=r["merchant"], category=r.get("category","Other"),
            note=r.get("note",""), cashback=r.get("cashback",0.0), source_file=source,
        ))
        inserted += 1
    db.commit()
    return inserted, skipped

def _parse_supermoney_df(df):
    results = []
    for _, row in df.iterrows():
        v = list(row)
        while len(v) < 8: v.append(None)
        merchant = (_s(v[0]) + (' ' + _s(v[1]) if _s(v[1]) else '')).strip()
        if not merchant: continue
        try: amount = float(str(v[4]).replace(',','').replace('+',''))
        except: continue
        d5,d6,d7 = _s(v[5]),_s(v[6]),_s(v[7])
        date_raw = f"{d5} {d6}" if re.match(r'^\d{4}$', d6) else d5
        status   = d7 if re.match(r'^\d{4}$', d6) else (d6 if d6 else d7)
        date_obj = _parser._parse_date(date_raw)
        if not date_obj: continue
        results.append({
            'date': date_obj.isoformat(), 'time': '00:00', 'amount': abs(amount),
            'transaction_type': 'sent' if amount < 0 else 'received',
            'merchant': merchant[:100], 'note': status, 'cashback': 0.0,
            'category': _parser._categorize_merchant(merchant),
        })
    return results


def _parse_gpay_csv(content: bytes) -> list[dict]:
    """
    GPay CSV format:
      col0: date ("02 Dec, 2025") or time or blank
      col1: description ("Paid to X" / "Received from X" / UPI ID / bank)
      col3 or col4: amount (₹2)
    Header rows at top are skipped automatically.
    """
    import csv as _csv, io as _io
    results = []

    def _pd(s):
        s = re.sub(r'[",]', '', s).strip()
        mm = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
              'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}
        m = re.match(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$', s)
        if not m: return None
        month = mm.get(m.group(2).lower()[:3])
        if not month: return None
        try: return datetime(int(m.group(3)), month, int(m.group(1)))
        except: return None

    def _amt(s):
        s = re.sub(r'[₹,\'\s]', '', str(s))
        try: return float(s)
        except: return None

    lines = content.decode('utf-8', errors='ignore').splitlines()
    i = 0
    while i < len(lines):
        try:
            row = next(_csv.reader([lines[i]]))
        except:
            row = lines[i].split(',')
        row = [c.strip() for c in row]
        while len(row) < 5: row.append('')

        date_obj = _pd(row[0])
        if date_obj:
            desc = row[1].strip()
            if any(x in desc.lower() for x in ['date', 'transaction detail', 'upi transaction']):
                i += 1; continue

            amount_raw = row[3] if row[3] else row[4]
            amount = _amt(amount_raw)

            txn_type = 'sent'
            merchant = desc
            if re.match(r'paid to', desc, re.I):
                txn_type = 'sent'
                merchant = re.sub(r'^paid to\s+', '', desc, flags=re.I).strip()
            elif re.match(r'received from', desc, re.I):
                txn_type = 'received'
                merchant = re.sub(r'^received from\s+', '', desc, flags=re.I).strip()

            # peek next line for time
            time_str = '00:00'
            if i + 1 < len(lines):
                next_row = lines[i+1].split(',')
                t = next_row[0].strip()
                if re.match(r'\d{1,2}:\d{2}\s*(AM|PM)', t, re.I):
                    time_str = t

            if amount and merchant:
                results.append({
                    'date': date_obj.isoformat(), 'time': time_str,
                    'amount': abs(amount),
                    'transaction_type': txn_type,
                    'merchant': merchant[:100], 'note': 'SUCCESS',
                    'cashback': 0.0,
                    'category': _parser._categorize_merchant(merchant),
                })
        i += 1
    return results


def _parse_phonepay_csv(content: bytes) -> list[dict]:
    """
    PhonePe CSV/TSV:
      Tab or comma separated
      Headers: Date, Time, Transaction Details, Transaction ID, UTR, Transaction Type, Credit/debit instrument, Amount
      Date format: "Jun 15, 2026"
      Transaction Type: CREDIT / DEBIT
    """
    import csv as _csv
    lines = content.decode('utf-8', errors='ignore').splitlines()
    results = []
    header_found = False
    month_map = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
                 'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}

    def _pd(s):
        s = re.sub(r'[",]', '', str(s)).strip()
        m = re.match(r'([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})', s)
        if not m: return None
        month = month_map.get(m.group(1).lower()[:3])
        if not month: return None
        try: return datetime(int(m.group(3)), month, int(m.group(2)))
        except: return None

    for raw_line in lines:
        # Try tab first, then csv
        if '\t' in raw_line:
            cols = [c.strip() for c in raw_line.split('\t')]
        else:
            try: cols = [c.strip().strip('"') for c in next(_csv.reader([raw_line]))]
            except: cols = [c.strip() for c in raw_line.split(',')]

        if not cols or not cols[0]: continue

        # Detect header row
        if cols[0].strip().lower() == 'date':
            header_found = True
            continue
        if not header_found: continue
        if len(cols) < 6: continue

        date_obj = _pd(cols[0])
        if not date_obj: continue

        time_str     = cols[1].strip() if len(cols) > 1 else '00:00'
        desc         = cols[2].strip() if len(cols) > 2 else ''
        txn_type_raw = cols[5].strip() if len(cols) > 5 else ''
        # Amount is last non-empty column (col 7, sometimes col 3)
        amount_raw = ''
        for i in [7, 6, 3]:
            if len(cols) > i and cols[i].strip():
                amount_raw = cols[i].strip()
                break

        # Skip header-like rows
        if desc.lower() in ['transaction details', 'date', '']: continue
        if 'upi transaction' in desc.lower(): continue

        try: amount = float(re.sub(r'[₹,\s]', '', amount_raw))
        except: continue
        if amount <= 0: continue

        txn_type = 'received' if 'credit' in txn_type_raw.lower() else 'sent'
        merchant = desc
        for prefix in ['received from ', 'paid to ', 'sent to ', 'payment to ', 'transferred to ', 'refund from ']:
            if desc.lower().startswith(prefix):
                merchant = desc[len(prefix):].strip()
                break

        if not merchant or merchant.lower() == 'nan': continue

        results.append({
            'date': date_obj.isoformat(), 'time': time_str,
            'amount': amount, 'transaction_type': txn_type,
            'merchant': merchant[:100], 'note': 'SUCCESS',
            'cashback': 0.0, 'category': _parser._categorize_merchant(merchant),
        })
    return results


def _query(db, user_id=None, date_from=None, date_to=None, all_rows=False):
    q = db.query(TransactionDB)
    if user_id: q = q.filter(TransactionDB.user_id == str(user_id))
    if date_from: q = q.filter(TransactionDB.date >= datetime.fromisoformat(date_from))
    if date_to:
        dt = date_to if 'T' in date_to else date_to + 'T23:59:59'
        q = q.filter(TransactionDB.date <= datetime.fromisoformat(dt))
    if not all_rows:
        try:
            q = q.filter(TransactionDB.included != False)
        except Exception:
            pass  # column may not exist in old DB
    return q.order_by(TransactionDB.date.desc()).all()


# ── AUTH ──────────────────────────────────────────────────────────────────────

class RegisterReq(BaseModel):
    email: str
    name:  str
    password: str

class LoginReq(BaseModel):
    email: str
    password: str

@app.post("/api/auth/register")
def register(req: RegisterReq, db: Session = Depends(get_db)):
    if db.query(UserDB).filter(UserDB.email == req.email).first():
        raise HTTPException(400, "Email already registered")
    user = UserDB(email=req.email, name=req.name, hashed_pw=hash_pw(req.password))
    db.add(user); db.commit(); db.refresh(user)
    token = create_token({"sub": user.email, "uid": user.id})
    return {"token": token, "user": {"id": user.id, "email": user.email, "name": user.name, "is_admin": bool(getattr(user, "is_admin", False))}}

@app.post("/api/auth/login")
def login(req: LoginReq, db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.email == req.email).first()
    if not user or not verify_pw(req.password, user.hashed_pw):
        raise HTTPException(401, "Invalid email or password")
    token = create_token({"sub": user.email, "uid": user.id})
    return {"token": token, "user": {"id": user.id, "email": user.email, "name": user.name, "is_admin": bool(getattr(user, "is_admin", False))}}

@app.get("/api/auth/me")
def me(user: UserDB = Depends(require_user)):
    return {"id": user.id, "email": user.email, "name": user.name}


# ── UPLOAD ───────────────────────────────────────────────────────────────────

@app.post("/api/upload")
async def upload_pdf(file: UploadFile = File(...),
                     db: Session = Depends(get_db),
                     user = Depends(get_current_user)):
    txns = _parser.parse_pdf(io.BytesIO(await file.read()))
    rows = [{**t.model_dump(), 'date': t.date.isoformat()} for t in txns]
    uid  = user.id if user else None
    ins, skp = _dedup_insert(db, rows, file.filename, uid)
    total = db.query(TransactionDB).filter(TransactionDB.user_id == (str(uid) if uid else None)).count()
    return JSONResponse(_safe({"count": len(rows), "inserted": ins, "skipped": skp, "total_stored": total}))

@app.post("/api/upload-csv")
async def upload_csv(file: UploadFile = File(...),
                     db: Session = Depends(get_db),
                     user = Depends(get_current_user)):
    content = await file.read()
    rows = []

    # 1. PhonePe (tab/comma, Date header, CREDIT/DEBIT column)
    try:
        rows = _parse_phonepay_csv(content)
        if rows: print(f"PhonePe: {len(rows)} txns")
    except Exception as e:
        print(f"PhonePe failed: {e}")

    # 2. GPay CSV ("Paid to/Received from" pattern)
    if not rows:
        try:
            rows = _parse_gpay_csv(content)
            if rows: print(f"GPay: {len(rows)} txns")
        except Exception as e:
            print(f"GPay failed: {e}")

    # 3. SuperMoney (positional, skiprows=1)
    if not rows:
        try:
            df = pd.read_csv(io.BytesIO(content), skiprows=1, header=None)
            rows = _parse_supermoney_df(df)
            if rows: print(f"SuperMoney: {len(rows)} txns")
        except: pass
    if not rows:
        for skip in [0,1,2]:
            try:
                df = pd.read_csv(io.BytesIO(content), skiprows=skip)
                df.columns = [str(c).strip().lower() for c in df.columns]
                df = df.replace({np.nan: None})
                nc = next((c for c in df.columns if any(x in c for x in ['name','merchant','description'])), None)
                ac = next((c for c in df.columns if 'amount' in c or 'amt' in c), None)
                dc = next((c for c in df.columns if 'date' in c), None)
                sc = next((c for c in df.columns if 'status' in c), None)
                if not all([nc,ac,dc]): continue
                for _,row in df.iterrows():
                    try:
                        m=str(row[nc]).strip(); a=float(str(row[ac]).replace(',','').replace('+','')); d=_parser._parse_date(str(row[dc]))
                        if not m or not d or m=='nan': continue
                        rows.append({'date':d.isoformat(),'time':'00:00','amount':abs(a),
                            'transaction_type':'sent' if a<0 else 'received','merchant':m[:100],
                            'note':str(row[sc]) if sc else '','cashback':0.0,'category':_parser._categorize_merchant(m)})
                    except: continue
                if rows: break
            except: continue
    if not rows: raise HTTPException(400, "Could not parse CSV")
    uid = user.id if user else None
    ins, skp = _dedup_insert(db, rows, file.filename, uid)
    total = db.query(TransactionDB).filter(TransactionDB.user_id == (str(uid) if uid else None)).count()
    return JSONResponse(_safe({"count": len(rows), "inserted": ins, "skipped": skp, "total_stored": total}))


# ── DATA ─────────────────────────────────────────────────────────────────────

@app.get("/api/transactions")
def get_transactions(date_from:str=None, date_to:str=None,
                     db:Session=Depends(get_db), user=Depends(get_current_user)):
    uid = user.id if user else None
    txns = _query(db, uid, date_from, date_to, all_rows=True)
    return JSONResponse(_safe({"transactions":[_row(t) for t in txns],"count":len(txns)}))

@app.delete("/api/transactions")
def clear(db:Session=Depends(get_db), user=Depends(get_current_user)):
    uid = user.id if user else None
    q = db.query(TransactionDB)
    if uid: q = q.filter(TransactionDB.user_id == str(uid))
    q.delete(); db.commit()
    return {"cleared": True}

@app.get("/api/analytics")
def analytics(date_from:str=None, date_to:str=None,
              db:Session=Depends(get_db), user=Depends(get_current_user)):
    uid = user.id if user else None
    txns = _query(db, uid, date_from, date_to)
    if not txns: raise HTTPException(404, "No transactions in selected range")
    objs = [Transaction(date=t.date, time=t.time, amount=t.amount,
                        transaction_type=t.transaction_type, merchant=t.merchant,
                        category=t.category, note=t.note, cashback=t.cashback) for t in txns]
    return JSONResponse(_safe(AnalyticsEngine(objs).get_analytics()))

@app.get("/api/date-range")
def date_range(db:Session=Depends(get_db), user=Depends(get_current_user)):
    uid = user.id if user else None
    q = db.query(func.min(TransactionDB.date), func.max(TransactionDB.date), func.count(TransactionDB.id))
    if uid: q = q.filter(TransactionDB.user_id == str(uid))
    row = q.first()
    return {"min": row[0].date().isoformat() if row[0] else None,
            "max": row[1].date().isoformat() if row[1] else None, "count": row[2]}


# ── RAG ───────────────────────────────────────────────────────────────────────

class RAGReq(BaseModel):
    question: str

@app.post("/api/rag/index")
def rag_index(date_from:str=None, date_to:str=None,
              db:Session=Depends(get_db), user=Depends(get_current_user)):
    uid = user.id if user else None
    txns = _query(db, uid, date_from, date_to)
    if not txns: raise HTTPException(400, "No transactions")
    return rag_service.index_transactions([_row(t) for t in txns],
                                          user_id=str(uid) if uid else "anon")

@app.post("/api/rag/query")
def rag_query(req: RAGReq, db: Session = Depends(get_db), user = Depends(get_current_user)):
    if not req.question.strip(): raise HTTPException(400, "Empty")
    uid  = user.id if user else None
    txns = _query(db, uid, all_rows=False)
    if not txns:
        return {"answer": "No transactions found. Upload a CSV first.", "sources": [], "provider": "none"}
    from .analytics import AnalyticsEngine
    from .models import Transaction
    objs = [Transaction(
        date=t.date, time=t.time, amount=t.amount,
        transaction_type=t.transaction_type,
        merchant=t.merchant,
        category=getattr(t, "custom_category", None) or t.category,
        note=t.note, cashback=t.cashback
    ) for t in txns]
    a = AnalyticsEngine(objs).get_analytics()
    # Date range for context
    dates = sorted([t.date for t in txns])
    date_range = ""
    if dates:
        date_range = f"{dates[0].strftime('%d %b %Y')} to {dates[-1].strftime('%d %b %Y')}"

    stats = {
        "total_transactions":  len(txns),
        "total_spent":         a.get("total_spent", 0),
        "total_received":      a.get("total_received", 0),
        "total_cashback":      a.get("total_cashback", 0),
        "highest_expense":     max((t.amount for t in objs if t.transaction_type == "sent"), default=0),
        "category_breakdown":  a.get("category_breakdown", {}),
        "top_merchants":       a.get("top_merchants", []),
        "top_received_sources": a.get("top_received_sources", []),
        "monthly_trend":       a.get("monthly_trend", {}),
        "recurring_merchants": a.get("recurring_merchants", []),
        "largest_transactions": a.get("largest_transactions", []),
        "date_range":          date_range,
    }
    return rag_service.query(req.question,
                              user_id=str(uid) if uid else "anon",
                              external_stats=stats)



@app.get("/api/rag/status")
def rag_status(db:Session=Depends(get_db), user=Depends(get_current_user)):
    uid = user.id if user else None
    idx = rag_service.get_indexed_count(str(uid) if uid else "anon")
    return {"ollama": rag_service.ollama_status(),
            "indexed_count": idx,
            "transactions_loaded": db.query(TransactionDB).filter(
                TransactionDB.user_id == (str(uid) if uid else None)
            ).count()}



class UpdateTxnReq(BaseModel):
    included: Optional[bool] = None
    category: Optional[str] = None

@app.patch("/api/transactions/{txn_id}")
def update_transaction(txn_id: int, req: UpdateTxnReq,
                       db: Session = Depends(get_db), user = Depends(get_current_user)):
    uid = user.id if user else None
    q = db.query(TransactionDB).filter(TransactionDB.id == txn_id)
    if uid: q = q.filter(TransactionDB.user_id == str(uid))
    t = q.first()
    if not t: raise HTTPException(404, "Transaction not found")

    if req.included is not None:
        t.included = req.included
    if req.category is not None:
        # Store as custom_category if different from auto-detected
        try:
            t.custom_category = req.category if req.category != t.category else None
        except Exception:
            pass  # column not yet in DB

    db.commit()
    return _row(t)


@app.get("/api/categories")
def get_categories(db: Session = Depends(get_db), user = Depends(get_current_user)):
    uid = user.id if user else None
    q = db.query(TransactionDB.custom_category).filter(TransactionDB.custom_category.isnot(None))
    if uid: q = q.filter(TransactionDB.user_id == str(uid))
    custom = list({r[0] for r in q.all() if r[0]})

    default = ['Credit Card','Healthcare','Travel','Shopping','Food & Grocery',
               'Transport','Utilities','Entertainment','Education','Transfer','Other']
    all_cats = sorted(set(default + custom))
    return {"categories": all_cats, "custom": custom}



class SMSSyncReq(BaseModel):
    transactions: list[dict]

@app.post("/api/sms/sync")
def sms_sync(req: SMSSyncReq, db: Session = Depends(get_db), user = Depends(get_current_user)):
    uid = user.id if user else None
    rows = []
    for t in req.transactions:
        dt = t.get("date")
        if isinstance(dt, str):
            try: dt = datetime.fromisoformat(dt)
            except: continue
        rows.append({
            "date": dt.isoformat(), "time": t.get("time","00:00"),
            "amount": float(t.get("amount",0)),
            "transaction_type": t.get("transaction_type","sent"),
            "merchant": str(t.get("merchant","Unknown"))[:100],
            "category": t.get("category","Other"),
            "note": t.get("note","SUCCESS"),
            "cashback": float(t.get("cashback",0)),
        })
    ins, skp = _dedup_insert(db, rows, "sms", uid)
    total = db.query(TransactionDB).filter(
        TransactionDB.user_id == (str(uid) if uid else None)
    ).count()
    return {"inserted": ins, "skipped": skp, "total_stored": total}



# ── CHANGE PASSWORD ───────────────────────────────────────────────────────────

class ChangePwReq(BaseModel):
    current_password: str
    new_password: str

@app.post("/api/auth/change-password")
def change_password(req: ChangePwReq, db: Session = Depends(get_db),
                    user = Depends(require_user)):
    if not verify_pw(req.current_password, user.hashed_pw):
        raise HTTPException(400, "Current password incorrect")
    user.hashed_pw = hash_pw(req.new_password)
    db.commit()
    return {"ok": True}


# ── ADMIN ─────────────────────────────────────────────────────────────────────

@app.get("/api/admin/stats")
def admin_stats(db: Session = Depends(get_db), admin = Depends(require_admin)):
    from sqlalchemy import func
    from datetime import timedelta
    now = datetime.utcnow()
    total_users  = db.query(func.count(UserDB.id)).scalar() or 0
    total_txns   = db.query(func.count(TransactionDB.id)).scalar() or 0
    online_users = db.query(func.count(UserDB.id)).filter(
        UserDB.last_seen >= now - timedelta(minutes=5)
    ).scalar() or 0
    new_today = db.query(func.count(UserDB.id)).filter(
        UserDB.created_at >= now.replace(hour=0, minute=0, second=0, microsecond=0)
    ).scalar() or 0
    return {
        "total_users":  total_users,
        "online_now":   online_users,
        "new_today":    new_today,
        "total_txns":   total_txns,
    }


@app.get("/api/admin/users")
def admin_users(db: Session = Depends(get_db), admin = Depends(require_admin)):
    from sqlalchemy import func
    from datetime import timedelta
    now   = datetime.utcnow()
    users = db.query(UserDB).all()
    result = []
    for u in users:
        txn_count = db.query(func.count(TransactionDB.id)).filter(
            TransactionDB.user_id == str(u.id)
        ).scalar() or 0
        latest = db.query(TransactionDB.date).filter(
            TransactionDB.user_id == str(u.id)
        ).order_by(TransactionDB.date.desc()).first()
        last     = getattr(u, "last_seen", None)
        online   = bool(last and (now - last).total_seconds() < 300)
        result.append({
            "id":              u.id,
            "email":           u.email,
            "name":            u.name,
            "is_admin":        bool(getattr(u, "is_admin", False)),
            "created_at":      u.created_at.isoformat() if u.created_at else None,
            "last_seen":       last.isoformat() if last else None,
            "online":          online,
            "txn_count":       txn_count,
            "latest_txn_date": latest[0].isoformat() if latest else None,
        })
    result.sort(key=lambda x: (x["online"], x["last_seen"] or ""), reverse=True)
    return {"users": result, "total": len(result),
            "online_now": sum(1 for u in result if u["online"])}


@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: int, db: Session = Depends(get_db),
                      admin = Depends(require_admin)):
    user = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if user.email == admin.email:
        raise HTTPException(400, "Cannot delete yourself")
    db.query(TransactionDB).filter(TransactionDB.user_id == str(user_id)).delete()
    db.delete(user)
    db.commit()
    return {"ok": True}

@app.get("/api/health")
def health(): return {"status": "ok"}
