import chromadb
from chromadb.utils import embedding_functions
import requests, re, os
from typing import Optional
import pandas as pd

GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL      = os.getenv("GROQ_MODEL", "llama3-8b-8192")
GROQ_URL        = "https://api.groq.com/openai/v1/chat"

# CLAUDE_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
# CLAUDE_MODEL    = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5")
# CLAUDE_URL      = "https://api.anthropic.com/v1/messages"

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "deepseek-r1:8b")

CHROMA_PATH     = "./chroma_db"
COLLECTION_NAME = "upi_transactions"

ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)

_client: Optional[chromadb.PersistentClient] = None
_collection = None

_MASKS = [
    (re.compile(r'\b[X*]{2,}\d{4}\b'),     '[ACCT]'),
    (re.compile(r'\b[\w.\-]+@[\w]+\b'),     '[UPI]'),
    (re.compile(r'\b[6-9]\d{9}\b'),         '[PHONE]'),
    (re.compile(r'\b\d{10,}\b'),            '[ID]'),
    (re.compile(r'\b[A-Z]{5}\d{4}[A-Z]\b'),'[PAN]'),
]

def mask(text: str) -> str:
    for p, r in _MASKS: text = p.sub(r, text)
    return text

def _get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=CHROMA_PATH)
        _collection = _client.get_or_create_collection(
            name=COLLECTION_NAME, embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection

def index_transactions(transactions: list[dict]) -> dict:
    col = _get_collection()
    if col.count() > 0:
        col.delete(ids=col.get()["ids"])
    docs, ids, metas = [], [], []
    for i, t in enumerate(transactions):
        amount   = float(t.get("amount", 0))
        txn_type = str(t.get("transaction_type", "sent"))
        category = str(t.get("category", "Other"))
        cashback = float(t.get("cashback", 0) or 0)
        month    = str(t.get("date", ""))[:7]
        direction = "outgoing" if txn_type == "sent" else "incoming"
        doc = f"Rs.{abs(amount):.0f} {direction} {category} in {month}."
        docs.append(doc); ids.append(f"txn_{i}")
        metas.append({"amount": amount, "transaction_type": txn_type,
                      "category": category, "cashback": cashback, "month": month})
    col.add(documents=docs, ids=ids, metadatas=metas)
    return {"indexed": len(docs), "status": "ok"}

def _compute_stats_from_chroma() -> dict:
    try:
        col = _get_collection()
        if col.count() == 0: return {}
        metas = col.get(include=["metadatas"])["metadatas"]
        df = pd.DataFrame(metas)
        sent = df[df["transaction_type"]=="sent"]["amount"].abs()
        recv = df[df["transaction_type"]=="received"]["amount"].abs()
        cat = {}
        if not sent.empty and "category" in df.columns:
            cat = {k: round(float(v),2) for k,v in
                   df[df["transaction_type"]=="sent"].groupby("category")["amount"]
                   .apply(lambda x: x.abs().sum()).sort_values(ascending=False).items()}
        return {
            "total_transactions": len(metas),
            "total_spent":    round(float(sent.sum()),2),
            "total_received": round(float(recv.sum()),2),
            "total_cashback": round(float(df["cashback"].sum()),2),
            "highest_expense": round(float(sent.max()),2) if not sent.empty else 0,
            "category_breakdown": cat,
        }
    except Exception as e:
        print(f"Chroma stats error: {e}"); return {}

# Accept external stats from SQLite (passed from main.py)
_external_stats: dict = {}

def set_stats(stats: dict):
    global _external_stats
    _external_stats = stats

def _get_stats() -> dict:
    return _external_stats or _compute_stats_from_chroma()

def _call_groq(prompt: str) -> Optional[str]:
    if not GROQ_API_KEY:
        print("GROQ_API_KEY not set")
        return None
    try:
        print(f"Calling Groq with model {GROQ_MODEL}...")
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": GROQ_MODEL,
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 400, "temperature": 0.3},
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()["choices"][0]["message"]["content"]
        print(f"Groq response received: {len(result)} chars")
        return result
    except Exception as e:
        print(f"Groq error: {type(e).__name__}: {e}")
        return None

# def _call_claude(prompt: str) -> Optional[str]:
#     if not CLAUDE_API_KEY: return None
#     try:
#         resp = requests.post(CLAUDE_URL,
#             headers={"x-api-key": CLAUDE_API_KEY,
#                      "anthropic-version": "2023-06-01",
#                      "content-type": "application/json"},
#             json={"model": CLAUDE_MODEL, "max_tokens": 400,
#                   "messages": [{"role": "user", "content": prompt}]},
#             timeout=30)
#         resp.raise_for_status()
#         return resp.json()["content"][0]["text"]
#     except Exception as e:
#         print(f"Claude error: {e}"); return None

def _call_ollama(prompt: str) -> Optional[str]:
    try:
        resp = requests.post(f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=30)
        resp.raise_for_status()
        return resp.json().get("response") or None
    except: return None

def _call_llm(prompt: str) -> str:
    result = _call_groq(prompt)  or _call_ollama(prompt)
    if result: return result
    keys = []
    if not GROQ_API_KEY:   keys.append("GROQ_API_KEY")
    # if not CLAUDE_API_KEY: keys.append("ANTHROPIC_API_KEY")
    if keys:
        return f"AI unavailable. Add {' or '.join(keys)} to Railway environment variables."
    return "AI service temporarily unavailable. Please try again."

def query(user_question: str, external_stats: dict = None) -> dict:
    stats = external_stats or _get_stats()

    if not stats:
        return {"answer": "No transaction data found. Upload a CSV and click Re-index.", "sources": []}

    total_spent = stats.get("total_spent", 0)
    cat = stats.get("category_breakdown", {})

    cat_lines = "\n".join(
        f"  {name}: Rs.{amt} ({round(amt/max(total_spent,1)*100)}%)"
        for name, amt in list(cat.items())[:8]
    ) or "  No category data"

    safe_q = mask(user_question)

    prompt = f"""You are a personal finance analyst. Analyze spending and answer concisely (3-4 sentences max). Use Rs. for amounts.

SPENDING SUMMARY (anonymized):
- Total spent:    Rs.{stats.get('total_spent',0)}
- Total received: Rs.{stats.get('total_received',0)}
- Net flow:       Rs.{round(stats.get('total_received',0) - stats.get('total_spent',0), 2)}
- Transactions:   {stats.get('total_transactions',0)}
- Largest single: Rs.{stats.get('highest_expense',0)}

Spending by category:
{cat_lines}

Question: {safe_q}
Answer:"""
# if CLAUDE_API_KEY else
    provider = "groq" if GROQ_API_KEY else ("claude"  "ollama")
    return {"answer": _call_llm(prompt), "sources": [], "stats": stats, "provider": provider}

def ollama_status() -> dict:
    if GROQ_API_KEY:
        return {"running": True, "models": [GROQ_MODEL],
                "active_model": GROQ_MODEL, "provider": "groq"}
    # if CLAUDE_API_KEY:
    #     return {"running": True, "models": [CLAUDE_MODEL],
    #             "active_model": CLAUDE_MODEL, "provider": "claude"}
    try:
        resp   = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        models = [m["name"] for m in resp.json().get("models", [])]
        return {"running": bool(models), "models": models,
                "active_model": OLLAMA_MODEL, "provider": "ollama"}
    except:
        return {"running": False, "models": [],
                "active_model": OLLAMA_MODEL, "provider": "none"}
