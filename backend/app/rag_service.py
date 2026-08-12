import os
import re
import requests
from typing import Optional
import pandas as pd

# ── Config ────────────────────────────────────────────────────────────────────

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "deepseek-r1:8b")


# ── Data masking ──────────────────────────────────────────────────────────────
# Dates, merchant/vendor names, categories, descriptions and amounts are NOT
# masked. Only potentially sensitive identifiers are masked.

_MASKS = [
    (re.compile(r"\b[X*]{2,}\d{4}\b"), "[ACCT]"),
    (re.compile(r"\b[\w.\-+]+@[\w.-]+\b"), "[UPI]"),
    (re.compile(r"(?<!\d)[6-9]\d{9}(?!\d)"), "[PHONE]"),
    (re.compile(r"(?<!\d)\d{10,}(?!\d)"), "[ID]"),
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[PAN]"),
]


def _mask(text: str) -> str:
    if not text:
        return text
    for pattern, replacement in _MASKS:
        text = pattern.sub(replacement, text)
    return text


# ── Groq call (OpenAI-compatible) ────────────────────────────────────────────

def _call_groq(prompt: str) -> Optional[str]:
    if not GROQ_API_KEY:
        print("GROQ_API_KEY not set in environment")
        return None

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
                "max_tokens": 400,
                "temperature": 0.3,
            },
            timeout=30,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
        print(f"Groq OK — {len(text)} chars")
        return text
    except Exception as e:
        print(f"Groq error: {e}")
        print(f"Response: {resp.text if 'resp' in locals() else 'no response'}")
        return None


# ── Ollama fallback (local only) ──────────────────────────────────────────────

def _call_ollama(prompt: str) -> Optional[str]:
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("response") or None
    except Exception:
        return None


def _call_llm(prompt: str) -> str:
    result = _call_groq(prompt)
    if result:
        return result

    result = _call_ollama(prompt)
    if result:
        return result

    if not GROQ_API_KEY:
        return "⚠ AI unavailable: GROQ_API_KEY not set in Railway environment variables."
    return "⚠ AI temporarily unavailable. Please try again."


# ── ChromaDB (optional — for local vector search) ────────────────────────────

_collection = None


def _get_collection():
    global _collection

    if _collection is None:
        try:
            import chromadb
            from chromadb.utils import embedding_functions

            ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )

            client = chromadb.PersistentClient(path="./chroma_db")
            _collection = client.get_or_create_collection(
                name="upi_transactions",
                embedding_function=ef,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as e:
            print(f"ChromaDB init error: {e}")
            return _collection

    return _collection


def index_transactions(transactions: list[dict]) -> dict:
    """
    Preserve existing RAG indexing functionality while keeping merchant/vendor
    names and complete dates available to the AI.
    """
    col = _get_collection()

    if col is None:
        return {"indexed": 0, "status": "chromadb unavailable"}

    if col.count() > 0:
        col.delete(ids=col.get()["ids"])

    docs, ids, metas = [], [], []

    for i, t in enumerate(transactions):
        amount = float(t.get("amount", 0))
        txn_type = str(t.get("transaction_type", "sent"))
        category = str(t.get("category", "Other"))
        date = str(t.get("date", ""))

        merchant = str(
            t.get("merchant")
            or t.get("vendor")
            or t.get("name")
            or t.get("Name")
            or "Unknown merchant"
        )

        direction = "outgoing" if txn_type == "sent" else "incoming"

        # Keep dates and merchant/vendor names visible. If a merchant string
        # contains a genuine sensitive identifier, only that identifier is masked.
        merchant_safe = _mask(merchant)

        docs.append(
            f"Transaction: Rs.{abs(amount):.2f}, "
            f"{direction}, "
            f"merchant/vendor: {merchant_safe}, "
            f"category: {category}, "
            f"date: {date}."
        )

        ids.append(f"txn_{i}")

        metas.append({
            "amount": amount,
            "transaction_type": txn_type,
            "category": category,
            "date": date,
            "merchant": merchant_safe,
        })

    col.add(documents=docs, ids=ids, metadatas=metas)

    return {"indexed": len(docs), "status": "ok"}


# ── Main query — stats come from SQLite via main.py ──────────────────────────

def query(user_question: str, external_stats: dict = None) -> dict:
    stats = external_stats or {}

    if not stats:
        return {
            "answer": "No transaction data found. Upload a CSV first.",
            "sources": [],
            "provider": "none",
        }

    total_spent = stats.get("total_spent", 0)
    cat = stats.get("category_breakdown", {})

    cat_lines = "\n".join(
        f"  {name}: Rs.{amt} ({round(amt / max(total_spent, 1) * 100)}%)"
        for name, amt in list(cat.items())[:8]
    ) or "  No category data"

    prompt = f"""You are a personal finance analyst. Answer in 3-4 sentences max. Use Rs.

SPENDING SUMMARY:

- Total spent:    Rs.{stats.get('total_spent', 0)}
- Total received: Rs.{stats.get('total_received', 0)}
- Net flow:       Rs.{round(stats.get('total_received', 0) - stats.get('total_spent', 0), 2)}
- Transactions:   {stats.get('total_transactions', 0)}
- Largest single: Rs.{stats.get('highest_expense', 0)}

By category:
{cat_lines}

Question: {_mask(user_question)}
Answer:"""

    provider = "groq" if GROQ_API_KEY else "ollama"

    return {
        "answer": _call_llm(prompt),
        "sources": [],
        "provider": provider,
    }


# ── Status ───────────────────────────────────────────────────────────────────

def ollama_status() -> dict:
    if GROQ_API_KEY:
        return {
            "running": True,
            "active_model": GROQ_MODEL,
            "provider": "groq",
            "models": [GROQ_MODEL],
        }

    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        models = [m["name"] for m in resp.json().get("models", [])]

        return {
            "running": bool(models),
            "active_model": OLLAMA_MODEL,
            "provider": "ollama",
            "models": models,
        }
    except Exception:
        return {
            "running": False,
            "active_model": OLLAMA_MODEL,
            "provider": "none",
            "models": [],
        }
