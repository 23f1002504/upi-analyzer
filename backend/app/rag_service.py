import chromadb
from chromadb.utils import embedding_functions
import requests, re, os
from typing import Optional
import pandas as pd

# ── Config ────────────────────────────────────────────────────────────────────
# Priority: 1) Groq (free, 14400/day, fast)  2) Claude API  3) Ollama (local)
GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL      = os.getenv("GROQ_MODEL", "llama3-8b-8192")
GROQ_URL        = "https://api.groq.com/openai/v1/chat/completions"

CLAUDE_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL    = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5")
CLAUDE_URL      = "https://api.anthropic.com/v1/messages"

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


# ── Data masking ──────────────────────────────────────────────────────────────
_MASKS = [
    (re.compile(r'\b[X*]{2,}\d{4}\b'),         '[ACCT]'),
    (re.compile(r'\b[\w.\-]+@[\w]+\b'),          '[UPI]'),
    (re.compile(r'\b[6-9]\d{9}\b'),              '[PHONE]'),
    (re.compile(r'\b\d{10,}\b'),                 '[ID]'),
    (re.compile(r'\b[A-Z]{5}\d{4}[A-Z]\b'),     '[PAN]'),
]

def mask(text: str) -> str:
    for pattern, replacement in _MASKS:
        text = pattern.sub(replacement, text)
    return text


# ── Index ─────────────────────────────────────────────────────────────────────
def index_transactions(transactions: list[dict]) -> dict:
    col = _get_collection()
    if col.count() > 0:
        col.delete(ids=col.get()["ids"])

    docs, ids, metas = [], [], []
    for i, t in enumerate(transactions):
        amount   = float(t.get("amount", 0))
        merchant = mask(str(t.get("merchant", "Unknown")))
        date     = str(t.get("date", ""))[:10]
        txn_type = str(t.get("transaction_type", "sent"))
        category = str(t.get("category", "Other"))
        cashback = float(t.get("cashback", 0) or 0)

        direction = "paid to" if txn_type == "sent" else "received from"
        doc = f"Txn {i+1}: Rs.{abs(amount):.0f} {direction} {merchant} on {date}. Category: {category}."
        docs.append(doc)
        ids.append(f"txn_{i}")
        metas.append({"amount": amount, "merchant": merchant, "date": date,
                      "transaction_type": txn_type, "category": category, "cashback": cashback})

    col.add(documents=docs, ids=ids, metadatas=metas)
    return {"indexed": len(docs), "status": "ok"}


# ── Retrieve ──────────────────────────────────────────────────────────────────
def retrieve(query: str, n: int = 8) -> list[dict]:
    col = _get_collection()
    if col.count() == 0: return []
    r = col.query(query_texts=[query], n_results=min(n, col.count()))
    return [{"document": d, "metadata": m} for d, m in zip(r["documents"][0], r["metadatas"][0])]


def _stats() -> dict:
    col = _get_collection()
    if col.count() == 0: return {}
    metas = col.get(include=["metadatas"])["metadatas"]
    df = pd.DataFrame(metas)
    sent = df[df["transaction_type"]=="sent"]["amount"].abs()
    recv = df[df["transaction_type"]=="received"]["amount"].abs()
    top  = (df[df["transaction_type"]=="sent"].groupby("merchant")["amount"]
            .apply(lambda x: x.abs().sum()).nlargest(5).to_dict())
    return {
        "total_transactions": len(metas),
        "total_spent":    round(float(sent.sum()), 2),
        "total_received": round(float(recv.sum()), 2),
        "total_cashback": round(float(df["cashback"].sum()), 2),
        "top_merchants":  {k: round(float(v), 2) for k, v in top.items()},
    }


# ── LLM calls ─────────────────────────────────────────────────────────────────
def _call_groq(prompt: str) -> Optional[str]:
    """Groq — free, 14400 req/day, very fast."""
    if not GROQ_API_KEY: return None
    try:
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 512, "temperature": 0.3},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"Groq error: {e}"); return None


def _call_claude(prompt: str) -> Optional[str]:
    """Claude API — zero data retention."""
    if not CLAUDE_API_KEY: return None
    try:
        resp = requests.post(
            CLAUDE_URL,
            headers={"x-api-key": CLAUDE_API_KEY, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": CLAUDE_MODEL, "max_tokens": 512,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]
    except Exception as e:
        print(f"Claude error: {e}"); return None


def _call_ollama(prompt: str) -> str:
    """Local Ollama — no data leaves your machine."""
    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json().get("response", "No response.")
    except requests.exceptions.ConnectionError:
        return "AI offline. Run `ollama serve` for local AI, or set GEMINI_API_KEY for free cloud AI."
    except Exception as e:
        return f"AI error: {str(e)}"


def _call_llm(prompt: str) -> str:
    return _call_groq(prompt) or _call_claude(prompt) or _call_ollama(prompt)


# ── Query ─────────────────────────────────────────────────────────────────────
def query(user_question: str) -> dict:
    col = _get_collection()
    if col.count() == 0:
        return {"answer": "No transactions indexed yet. Upload a CSV first.", "sources": []}

    safe_q = mask(user_question)
    hits   = retrieve(safe_q)
    stats  = _stats()

    prompt = f"""You are a UPI transaction analyst. Answer using ONLY the data below. Use Rs. for amounts. Be concise.

Summary: {stats['total_transactions']} transactions, Rs.{stats['total_spent']} spent, Rs.{stats['total_received']} received.

Relevant transactions:
{chr(10).join(f"- {h['document']}" for h in hits)}

Question: {safe_q}
Answer:"""

    provider = "groq" if GROQ_API_KEY else ("claude" if CLAUDE_API_KEY else "ollama")
    return {"answer": _call_llm(prompt), "sources": [h["document"] for h in hits[:3]],
            "stats": stats, "provider": provider}


# ── Status ────────────────────────────────────────────────────────────────────
def ollama_status() -> dict:
    if GROQ_API_KEY:
        return {"running": True, "models": [GROQ_MODEL], "active_model": GROQ_MODEL, "provider": "groq"}
    if CLAUDE_API_KEY:
        return {"running": True, "models": [CLAUDE_MODEL], "active_model": CLAUDE_MODEL, "provider": "claude"}
    try:
        resp   = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        models = [m["name"] for m in resp.json().get("models", [])]
        return {"running": bool(models), "models": models, "active_model": OLLAMA_MODEL, "provider": "ollama"}
    except:
        return {"running": False, "models": [], "active_model": OLLAMA_MODEL, "provider": "none"}
