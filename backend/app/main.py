from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Query, Form
from typing import Optional
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
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
                   get_current_user, require_user)
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
    return {
        "id": t.id, "date": t.date.isoformat(), "time": t.time,
        "amount": t.amount, "transaction_type": t.transaction_type,
        "merchant": t.merchant,
        "category": t.custom_category or t.category,
        "base_category": t.category,
        "custom_category": t.custom_category,
        "note": t.note, "cashback": t.cashback,
        "included": t.included if t.included is not None else True,
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


def _query(db, user_id=None, date_from=None, date_to=None, all_rows=False):
    q = db.query(TransactionDB)
    if user_id: q = q.filter(TransactionDB.user_id == str(user_id))
    if date_from: q = q.filter(TransactionDB.date >= datetime.fromisoformat(date_from))
    if date_to:
        dt = date_to if 'T' in date_to else date_to + 'T23:59:59'
        q = q.filter(TransactionDB.date <= datetime.fromisoformat(dt))
    if not all_rows:
        q = q.filter(TransactionDB.included != False)
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
    return {"token": token, "user": {"id": user.id, "email": user.email, "name": user.name}}

@app.post("/api/auth/login")
def login(req: LoginReq, db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.email == req.email).first()
    if not user or not verify_pw(req.password, user.hashed_pw):
        raise HTTPException(401, "Invalid email or password")
    token = create_token({"sub": user.email, "uid": user.id})
    return {"token": token, "user": {"id": user.id, "email": user.email, "name": user.name}}

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

    # Try GPay CSV (has date in col0, "Paid to/Received from" in col1)
    try:
        gpay_rows = _parse_gpay_csv(content)
        if gpay_rows:
            rows = gpay_rows
            print(f"GPay CSV: {len(rows)} transactions")
    except Exception as e:
        print(f"GPay CSV failed: {e}")

    # Try SuperMoney CSV
    if not rows:
        try:
            df = pd.read_csv(io.BytesIO(content), skiprows=1, header=None)
            rows = _parse_supermoney_df(df)
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
    return rag_service.index_transactions([_row(t) for t in txns])

@app.post("/api/rag/query")
def rag_query(req: RAGReq):
    if not req.question.strip(): raise HTTPException(400, "Empty")
    return rag_service.query(req.question)

@app.get("/api/rag/status")
def rag_status(db:Session=Depends(get_db)):
    col = rag_service._get_collection()
    return {"ollama": rag_service.ollama_status(),
            "indexed_count": col.count(),
            "transactions_loaded": db.query(TransactionDB).count()}



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
        t.custom_category = req.category if req.category != t.category else None

    db.commit()

    # Return updated row + refreshed categories list
    row = _row(t)

    # Fetch updated categories
    cq = db.query(TransactionDB.custom_category).filter(TransactionDB.custom_category.isnot(None))
    if uid: cq = cq.filter(TransactionDB.user_id == str(uid))
    custom = sorted({r[0] for r in cq.all() if r[0]})
    default = ['Credit Card','Education','Entertainment','Food & Grocery',
               'Healthcare','Other','Shopping','Transfer','Transport','Travel','Utilities']
    row['all_categories'] = sorted(set(default + custom))

    return row


@app.get("/api/categories")
def get_categories(db: Session = Depends(get_db), user = Depends(get_current_user)):
    uid = user.id if user else None

    # Get all unique custom categories for this user
    q = db.query(TransactionDB.custom_category).filter(TransactionDB.custom_category.isnot(None))
    if uid: q = q.filter(TransactionDB.user_id == str(uid))
    custom = sorted({r[0] for r in q.all() if r[0]})

    default = ['Credit Card','Education','Entertainment','Food & Grocery',
               'Healthcare','Other','Shopping','Transfer','Transport','Travel','Utilities']
    all_cats = sorted(set(default + custom))
    return {"categories": all_cats, "custom": custom}


class SaveCategoryReq(BaseModel):
    name: str

@app.post("/api/categories")
def save_category(req: SaveCategoryReq, db: Session = Depends(get_db), user = Depends(get_current_user)):
    """Explicitly save a custom category (for future use without needing a transaction)."""
    name = req.name.strip()
    if not name or len(name) > 50:
        raise HTTPException(400, "Invalid category name")
    # We store categories implicitly via transactions — just return updated list
    uid = user.id if user else None
    q = db.query(TransactionDB.custom_category).filter(TransactionDB.custom_category.isnot(None))
    if uid: q = q.filter(TransactionDB.user_id == str(uid))
    custom = sorted({r[0] for r in q.all() if r[0]})
    default = ['Credit Card','Education','Entertainment','Food & Grocery',
               'Healthcare','Other','Shopping','Transfer','Transport','Travel','Utilities']
    all_cats = sorted(set(default + custom + [name]))
    return {"categories": all_cats, "custom": sorted(set(custom + [name]))}



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

@app.get("/api/health")
def health(): return {"status": "ok"}
