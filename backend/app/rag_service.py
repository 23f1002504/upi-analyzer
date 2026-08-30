"""
RAG Service — proper implementation:
1. Per-user ChromaDB collections (no cross-user data)
2. Real vector embeddings via all-MiniLM-L6-v2
3. Semantic retrieval + aggregate stats both sent to Groq
4. Merchant names + dates sent to Groq, only acct/UPI/phone masked
"""
import os, re, requests
from typing import Optional
import pandas as pd

# ── Config ────────────────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")  # loaded at import
GROQ_MODEL   = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"
OLLAMA_URL   = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "deepseek-r1:8b")
CHROMA_PATH  = "./chroma_db"

# ── Masking — only truly sensitive fields ─────────────────────────────────────
_MASKS = [
    (re.compile(r'\b[X*]{2,}\d{4}\b'),      '[ACCT]'),
    (re.compile(r'\b[\w.\-]+@[\w]+\b'),      '[UPI]'),
    (re.compile(r'\b[6-9]\d{9}\b'),          '[PHONE]'),
    (re.compile(r'\b\d{12,}\b'),             '[ID]'),
    (re.compile(r'\b[A-Z]{5}\d{4}[A-Z]\b'), '[PAN]'),
]

def _mask(text: str) -> str:
    for p, r in _MASKS:
        text = p.sub(r, text)
    return text


# ── ChromaDB — per-user collections ──────────────────────────────────────────
_chroma_client = None
_ef            = None

def _get_chroma():
    global _chroma_client, _ef
    if _chroma_client is None:
        try:
            import chromadb
            from chromadb.utils import embedding_functions
            _ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )
            _chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
            print("ChromaDB initialized")
        except Exception as e:
            print(f"ChromaDB unavailable: {e}")
    return _chroma_client, _ef


def _get_user_collection(user_id: str):
    """Each user gets their own ChromaDB collection — complete isolation."""
    client, ef = _get_chroma()
    if client is None:
        return None
    safe_uid = str(user_id).replace("-", "_")
    col_name = f"user_{safe_uid}"
    try:
        return client.get_or_create_collection(
            name=col_name,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
    except Exception as e:
        print(f"Collection error: {e}")
        return None


def index_transactions(transactions: list[dict], user_id: str = None) -> dict:
    """
    Index transactions into user-specific ChromaDB collection.
    Each chunk = one transaction with merchant name, category, date, amount.
    """
    col = _get_user_collection(user_id or "anon")
    if col is None:
        return {"indexed": 0, "status": "chromadb unavailable"}

    # Clear existing user data
    try:
        existing = col.get()
        if existing["ids"]:
            col.delete(ids=existing["ids"])
    except: pass

    docs, ids, metas = [], [], []
    for i, t in enumerate(transactions):
        amount   = float(t.get("amount", 0))
        txn_type = str(t.get("transaction_type", "sent"))
        merchant = _mask(str(t.get("merchant", "Unknown")))  # mask acct refs in names
        category = str(t.get("category", "Other"))
        date     = str(t.get("date", ""))[:10]
        note     = str(t.get("note", ""))

        direction = "paid to" if txn_type == "sent" else "received from"

        # Rich document — merchant name + category + date for semantic search
        doc = (
            f"Rs.{abs(amount):.0f} {direction} {merchant} on {date}. "
            f"Category: {category}."
            + (f" Status: {note}." if note and note != "nan" else "")
        )

        docs.append(doc)
        ids.append(f"t_{i}")
        metas.append({
            "amount":           amount,
            "transaction_type": txn_type,
            "merchant":         merchant,
            "category":         category,
            "date":             date,
        })

    if docs:
        col.add(documents=docs, ids=ids, metadatas=metas)

    print(f"Indexed {len(docs)} transactions for user {user_id}")
    return {"indexed": len(docs), "status": "ok"}


def retrieve(question: str, user_id: str, n: int = 10) -> list[dict]:
    """Semantic search — finds most relevant transactions for the question."""
    col = _get_user_collection(user_id or "anon")
    if col is None or col.count() == 0:
        return []
    try:
        results = col.query(
            query_texts=[question],
            n_results=min(n, col.count()),
        )
        return [
            {"document": d, "metadata": m}
            for d, m in zip(
                results["documents"][0],
                results["metadatas"][0],
            )
        ]
    except Exception as e:
        print(f"Retrieval error: {e}")
        return []


def get_indexed_count(user_id: str) -> int:
    col = _get_user_collection(user_id or "anon")
    if col is None:
        return 0
    try:
        return col.count()
    except:
        return 0


# ── LLM calls ─────────────────────────────────────────────────────────────────
def _call_groq(prompt: str) -> Optional[str]:
    key = os.getenv("GROQ_API_KEY", GROQ_API_KEY)
    model = os.getenv("GROQ_MODEL", GROQ_MODEL)
    if not key:
        print("GROQ_API_KEY not set")
        return None
    try:
        resp = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type":  "application/json",
            },
            json={
                "model":       model,
                "messages":    [{"role": "user", "content": prompt}],
                "max_tokens":  512,
                "temperature": 0.3,
            },
            timeout=30,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
        print(f"Groq OK — {len(text)} chars")
        return text
    except Exception as e:
        print(f"Groq error type: {type(e).__name__}")
        print(f"Groq error: {e}")
        try:
            print(f"Groq response body: {resp.text[:500]}")
        except: pass
        return None


def _call_ollama(prompt: str) -> Optional[str]:
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("response") or None
    except:
        return None


def _call_llm(prompt: str) -> str:
    result = _call_groq(prompt) or _call_ollama(prompt)
    if result:
        return result
    if not GROQ_API_KEY:
        return "AI unavailable: GROQ_API_KEY not set in Railway environment variables."
    return "AI temporarily unavailable. Please try again."


# ── Main query — RAG + aggregate stats ────────────────────────────────────────
def query(user_question: str, user_id: str = None,
          external_stats: dict = None) -> dict:
    """
    Full RAG pipeline:
    1. Semantic retrieval from user's ChromaDB collection
    2. Aggregate stats from SQLite (passed via external_stats)
    3. Both sent to Groq — gives specific + contextual answers
    """
    stats = external_stats or {}

    if not stats:
        return {
            "answer":   "No transaction data. Upload a CSV first.",
            "sources":  [],
            "provider": "none",
        }

    # ── Step 1: Semantic retrieval ────────────────────────────────────────────
    hits = []
    if user_id:
        hits = retrieve(user_question, user_id, n=10)

    retrieved_docs = "\n".join(f"  • {h['document']}" for h in hits)
    if not retrieved_docs:
        retrieved_docs = "  (Index not built — click Re-index for transaction-level answers)"

    # ── Step 2: Aggregate context ─────────────────────────────────────────────
    total_spent    = stats.get("total_spent", 0)
    total_received = stats.get("total_received", 0)
    cat            = stats.get("category_breakdown", {})
    top_merchants  = stats.get("top_merchants", [])
    monthly        = stats.get("monthly_trend", {})
    recurring      = stats.get("recurring_merchants", [])
    largest        = stats.get("largest_transactions", [])
    date_range     = stats.get("date_range", "")

    cat_lines = "\n".join(
        f"  {k}: Rs.{v} ({round(v/max(total_spent,1)*100)}%)"
        for k, v in list(cat.items())[:8]
    ) or "  No data"

    merchant_lines = "\n".join(
        f"  {m['name']}: Rs.{m['spent']} ({m['count']} times)"
        for m in top_merchants[:6]
    ) or "  No data"

    monthly_lines = "\n".join(
        f"  {mo}: Rs.{amt}"
        for mo, amt in list(monthly.items())[-6:]
    ) or "  No data"

    recurring_lines = "\n".join(
        f"  {r['merchant']}: Rs.{r['avg']:.0f}/time × {r['count']} = Rs.{r['total']:.0f}"
        for r in recurring[:4]
    ) or "  None"

    largest_lines = "\n".join(
        f"  {t['merchant']}: Rs.{t['amount']} on {t['date']}"
        for t in largest[:4]
    ) or "  None"

    safe_q = _mask(user_question)

    # ── Step 3: Build prompt ──────────────────────────────────────────────────
    # Trim lists to keep prompt under ~3000 tokens
    top_merchants  = top_merchants[:5]
    recurring      = recurring[:3]
    largest        = largest[:3]

    prompt = f"""You are a personal finance analyst. Give specific, actionable answers. Use Rs. Max 4-5 sentences.

PERIOD: {date_range or "All available data"}
TOTAL SPENT: Rs.{total_spent} | RECEIVED: Rs.{total_received} | NET: Rs.{round(total_received-total_spent,2)}
TRANSACTIONS: {stats.get('total_transactions',0)}

SPENDING BY CATEGORY:
{cat_lines}

TOP MERCHANTS:
{merchant_lines}

MONTHLY TREND:
{monthly_lines}

RECURRING PAYMENTS:
{recurring_lines}

LARGEST PAYMENTS:
{largest_lines}

SEMANTICALLY RELEVANT TRANSACTIONS (from vector search):
{retrieved_docs}

QUESTION: {safe_q}
ANSWER:"""

    provider = "groq" if GROQ_API_KEY else "ollama"
    answer   = _call_llm(prompt)

    return {
        "answer":   answer,
        "sources":  [h["document"] for h in hits[:3]],
        "provider": provider,
        "indexed":  len(hits),
    }


# ── Status ────────────────────────────────────────────────────────────────────
def ollama_status() -> dict:
    # Re-read at call time in case env was set after import
    key = os.getenv("GROQ_API_KEY", GROQ_API_KEY)
    model = os.getenv("GROQ_MODEL", GROQ_MODEL)
    print(f"Status check - GROQ key present: {bool(key)}")
    if key:
        return {
            "running":      True,
            "active_model": model,
            "provider":     "groq",
            "models":       [model],
        }
    try:
        resp   = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        models = [m["name"] for m in resp.json().get("models", [])]
        return {
            "running":      bool(models),
            "active_model": OLLAMA_MODEL,
            "provider":     "ollama",
            "models":       models,
        }
    except:
        return {
            "running":      False,
            "active_model": OLLAMA_MODEL,
            "provider":     "none",
            "models":       [],
        }
