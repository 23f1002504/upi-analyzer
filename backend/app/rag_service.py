import chromadb
from chromadb.utils import embedding_functions
import requests, re, os
from typing import Optional
import pandas as pd

# ── Config ────────────────────────────────────────────────────────────────────
GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL      = os.getenv("GROQ_MODEL", "llama3-8b-8192")  # free, fast
GROQ_URL        = "https://api.groq.com/openai/v1/chat/completions"

# Ollama fallback (local dev)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "deepseek-r1:8b")

CHROMA_PATH     = "./chroma_db"
COLLECTION_NAME = "upi_transactions"

ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)

_client: Optional[chromadb.PersistentClient] = None
_collection = None


def _get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=CHROMA_PATH)
        _collection = _client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


# ── Data masking ─────────────────────────────────────────────────────────────
_MASK_PATTERNS = [
    # Account numbers: XXXXXX9299, **1234, XX1234
    (re.compile(r'\b[X*]{2,}\d{4}\b'), '[ACCOUNT]'),
    # UPI IDs: abc@upi, name@okicici
    (re.compile(r'\b[\w.\-]+@[\w]+\b'), '[UPI_ID]'),
    # Phone numbers: 10-digit Indian
    (re.compile(r'\b[6-9]\d{9}\b'), '[PHONE]'),
    # Transaction IDs (long numeric)
    (re.compile(r'\b\d{10,}\b'), '[TXN_ID]'),
    # PAN-like: ABCDE1234F
    (re.compile(r'\b[A-Z]{5}\d{4}[A-Z]\b'), '[PAN]'),
    # Names in merchants that look like full names (2+ words, title case)
    # We keep these — they're merchant names, not PII
]

def mask_sensitive(text: str) -> str:
    for pattern, replacement in _MASK_PATTERNS:
        text = pattern.sub(replacement, text)
    return text

def mask_transaction(t: dict) -> dict:
    """Return a copy of transaction with sensitive fields masked."""
    return {
        "amount":           t.get("amount", 0),
        "transaction_type": t.get("transaction_type", ""),
        "merchant":         mask_sensitive(str(t.get("merchant", ""))),
        "category":         t.get("category", ""),
        "date":             str(t.get("date", ""))[:10],  # date only, no time
        "cashback":         t.get("cashback", 0),
    }


# ── Index ─────────────────────────────────────────────────────────────────────
def index_transactions(transactions: list[dict]) -> dict:
    col = _get_collection()
    if col.count() > 0:
        col.delete(ids=col.get()["ids"])

    docs, ids, metas = [], [], []
    for i, t in enumerate(transactions):
        mt = mask_transaction(t)
        amount   = float(mt["amount"])
        merchant = mt["merchant"]
        date     = mt["date"]
        txn_type = mt["transaction_type"]
        category = mt["category"]
        cashback = float(mt["cashback"])

        direction = "paid to" if txn_type == "sent" else "received from"
        doc = (f"Transaction {i+1}: Rs.{abs(amount):.0f} {direction} {merchant} "
               f"on {date}. Category: {category}.")

        docs.append(doc)
        ids.append(f"txn_{i}")
        metas.append({
            "amount": amount, "merchant": merchant, "date": date,
            "transaction_type": txn_type, "category": category, "cashback": cashback,
        })

    col.add(documents=docs, ids=ids, metadatas=metas)
    return {"indexed": len(docs), "status": "ok"}


# ── Retrieve ──────────────────────────────────────────────────────────────────
def retrieve(query: str, n_results: int = 10) -> list[dict]:
    col = _get_collection()
    if col.count() == 0:
        return []
    results = col.query(query_texts=[query], n_results=min(n_results, col.count()))
    return [{"document": d, "metadata": m}
            for d, m in zip(results["documents"][0], results["metadatas"][0])]


def _compute_stats() -> dict:
    col = _get_collection()
    if col.count() == 0:
        return {}
    metas = col.get(include=["metadatas"])["metadatas"]
    df    = pd.DataFrame(metas)
    sent     = df[df["transaction_type"] == "sent"]["amount"].abs()
    received = df[df["transaction_type"] == "received"]["amount"].abs()
    top = (df[df["transaction_type"] == "sent"]
           .groupby("merchant")["amount"].apply(lambda x: x.abs().sum())
           .nlargest(5).to_dict())
    return {
        "total_transactions": len(metas),
        "total_spent":        round(float(sent.sum()), 2),
        "total_received":     round(float(received.sum()), 2),
        "total_cashback":     round(float(df["cashback"].sum()), 2),
        "highest_expense":    round(float(sent.max()), 2) if not sent.empty else 0,
        "top_merchants":      {k: round(float(v), 2) for k, v in top.items()},
    }


# ── LLM calls ─────────────────────────────────────────────────────────────────
def _call_groq(prompt: str) -> str:
    if not GROQ_API_KEY:
        return None  # fallback to Ollama
    try:
        resp = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 512,
                "temperature": 0.3,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"Groq error: {e}")
        return None


def _call_ollama(prompt: str) -> str:
    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json().get("response", "No response.")
    except requests.exceptions.ConnectionError:
        return "⚠️ AI unavailable. Run `ollama serve` locally or set GROQ_API_KEY."
    except Exception as e:
        return f"⚠️ AI error: {str(e)}"


def _call_llm(prompt: str) -> str:
    # Try Groq first (fast, free), fallback to Ollama
    result = _call_groq(prompt)
    if result:
        return result
    return _call_ollama(prompt)


# ── Query ─────────────────────────────────────────────────────────────────────
def query(user_question: str) -> dict:
    col = _get_collection()
    if col.count() == 0:
        return {"answer": "No transactions indexed yet. Upload a CSV first.", "sources": []}

    # Mask the question too (in case user pastes account numbers)
    safe_question = mask_sensitive(user_question)

    hits  = retrieve(safe_question, n_results=8)
    stats = _compute_stats()

    prompt = f"""You are a UPI transaction analyst. Answer ONLY using the data below.
Use Rs. for amounts. Be concise (2-4 sentences max).

Summary: {stats['total_transactions']} transactions, Rs.{stats['total_spent']} spent, Rs.{stats['total_received']} received.

Relevant transactions:
{chr(10).join(f"- {h['document']}" for h in hits)}

Question: {safe_question}
Answer:"""

    return {
        "answer":  _call_llm(prompt),
        "sources": [h["document"] for h in hits[:3]],
        "stats":   stats,
        "provider": "groq" if GROQ_API_KEY else "ollama",
    }


# ── Status ────────────────────────────────────────────────────────────────────
def ollama_status() -> dict:
    groq_ok = bool(GROQ_API_KEY)
    if groq_ok:
        return {"running": True, "models": [GROQ_MODEL], "active_model": GROQ_MODEL, "provider": "groq"}
    try:
        resp   = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        models = [m["name"] for m in resp.json().get("models", [])]
        return {"running": True, "models": models, "active_model": OLLAMA_MODEL, "provider": "ollama"}
    except Exception:
        return {"running": False, "models": [], "active_model": OLLAMA_MODEL, "provider": "none"}
