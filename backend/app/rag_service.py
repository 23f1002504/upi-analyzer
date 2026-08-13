import os
import re
import requests
from typing import Optional, Any

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
    """Mask only sensitive identifiers; leave dates and merchant names intact."""
    if not text:
        return text
    text = str(text)
    for pattern, replacement in _MASKS:
        text = pattern.sub(replacement, text)
    return text


# ── Groq / Ollama ─────────────────────────────────────────────────────────────

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
                "max_tokens": 500,
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


# ── ChromaDB ──────────────────────────────────────────────────────────────────
# One collection is shared physically, but EVERY record is tagged with user_id.
# Retrieval and deletion are always filtered by user_id.
#
# IMPORTANT:
# - If user_id is missing, this module will NOT index or retrieve vectors.
# - This prevents accidental cross-user access from old call sites.
# - ChromaDB generates embeddings through SentenceTransformerEmbeddingFunction.

_collection = None
_embedding_function = None


def _get_collection():
    global _collection, _embedding_function

    if _collection is not None:
        return _collection

    try:
        import chromadb
        from chromadb.utils import embedding_functions

        _embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )

        client = chromadb.PersistentClient(path="./chroma_db")
        _collection = client.get_or_create_collection(
            name="upi_transactions",
            embedding_function=_embedding_function,
            metadata={"hnsw:space": "cosine"},
        )
        return _collection

    except Exception as e:
        print(f"ChromaDB init error: {e}")
        _collection = None
        return None


def chromadb_status() -> dict:
    """Small diagnostic helper; safe to expose from a health/status endpoint."""
    col = _get_collection()
    if col is None:
        return {
            "available": False,
            "count": 0,
            "embeddings": "unavailable",
        }

    try:
        return {
            "available": True,
            "count": col.count(),
            "embeddings": "sentence-transformers/all-MiniLM-L6-v2",
        }
    except Exception:
        return {
            "available": True,
            "count": 0,
            "embeddings": "sentence-transformers/all-MiniLM-L6-v2",
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _merchant(t: dict) -> str:
    return str(
        t.get("merchant")
        or t.get("vendor")
        or t.get("name")
        or t.get("Name")
        or "Unknown merchant"
    ).strip()


def _safe_user_id(user_id: Any) -> Optional[str]:
    """
    Normalize the authenticated user's ID.

    Never derive this from the question, merchant, email, or transaction data.
    It must come from the authenticated backend request.
    """
    if user_id is None:
        return None

    value = str(user_id).strip()
    return value if value else None


def _delete_user_vectors(col, user_id: str) -> int:
    """Delete only the authenticated user's vectors."""
    existing = col.get(
        where={"user_id": str(user_id)},
        include=[],
    )
    ids = existing.get("ids") or []

    if ids:
        col.delete(ids=ids)

    return len(ids)


# ── User-isolated indexing ────────────────────────────────────────────────────

def index_transactions(transactions: list[dict], user_id: Any = None) -> dict:
    """
    Index one user's transactions into ChromaDB.

    Backward-compatible call:
        index_transactions(transactions)

    However, without user_id nothing is indexed. This is intentional: a
    global vector index is unsafe for a multi-user application.

    Preferred call:
        index_transactions(transactions, user_id=current_user_id)
    """
    uid = _safe_user_id(user_id)

    if not uid:
        return {
            "indexed": 0,
            "deleted": 0,
            "status": "user_id required for isolated ChromaDB indexing",
        }

    col = _get_collection()

    if col is None:
        return {
            "indexed": 0,
            "deleted": 0,
            "status": "chromadb unavailable",
        }

    try:
        deleted = _delete_user_vectors(col, uid)

        docs = []
        ids = []
        metas = []

        for i, t in enumerate(transactions or []):
            try:
                amount = float(t.get("amount", 0) or 0)
            except (TypeError, ValueError):
                amount = 0.0

            txn_type = str(t.get("transaction_type", "sent") or "sent").lower()
            category = str(t.get("category", "Other") or "Other")
            date = str(t.get("date", "") or "")
            merchant = _merchant(t)
            description = str(
                t.get("description")
                or t.get("remarks")
                or t.get("note")
                or ""
            ).strip()

            direction = "outgoing" if txn_type in {
                "sent", "debit", "paid", "payment", "expense"
            } else "incoming"

            # Merchant/date are preserved. Only genuine sensitive identifiers
            # inside a merchant/description are masked.
            merchant_safe = _mask(merchant)
            description_safe = _mask(description)

            document = (
                f"Transaction: Rs.{abs(amount):.2f}; "
                f"direction: {direction}; "
                f"merchant/vendor: {merchant_safe}; "
                f"category: {category}; "
                f"date: {date}; "
                f"description: {description_safe}."
            )

            # IDs are unique across users and re-imports.
            txn_id = str(
                t.get("id")
                or t.get("transaction_id")
                or t.get("transactionId")
                or f"{i}"
            )
            vector_id = f"user_{uid}_txn_{txn_id}_{i}"

            docs.append(document)
            ids.append(vector_id)
            metas.append({
                "user_id": uid,
                "transaction_id": txn_id,
                "amount": amount,
                "transaction_type": txn_type,
                "category": category,
                "date": date,
                "merchant": merchant_safe,
                "description": description_safe,
            })

        if docs:
            col.add(
                documents=docs,
                ids=ids,
                metadatas=metas,
            )

        return {
            "indexed": len(docs),
            "deleted": deleted,
            "status": "ok",
        }

    except Exception as e:
        print(f"ChromaDB indexing error for user {uid}: {e}")
        return {
            "indexed": 0,
            "deleted": 0,
            "status": "error",
            "error": str(e),
        }


# ── User-isolated semantic retrieval ─────────────────────────────────────────

def search_transactions(
    user_id: Any,
    question: str,
    n_results: int = 8,
) -> list[dict]:
    """
    Semantic vector search restricted to ONE authenticated user.

    The user_id filter is mandatory. There is deliberately no global fallback.
    """
    uid = _safe_user_id(user_id)
    if not uid or not question:
        return []

    col = _get_collection()
    if col is None:
        return []

    try:
        total = col.count()
        if total <= 0:
            return []

        n = max(1, min(int(n_results or 8), 20))

        result = col.query(
            query_texts=[_mask(question)],
            n_results=n,
            where={"user_id": uid},
        )

        documents = (result.get("documents") or [[]])[0] or []
        metadatas = (result.get("metadatas") or [[]])[0] or []
        distances = (result.get("distances") or [[]])[0] or []

        rows = []
        for i, document in enumerate(documents):
            metadata = metadatas[i] if i < len(metadatas) else {}
            distance = distances[i] if i < len(distances) else None

            rows.append({
                "document": document,
                "metadata": metadata or {},
                "distance": distance,
            })

        return rows

    except Exception as e:
        print(f"ChromaDB query error for user {uid}: {e}")
        return []


def _format_retrieved_context(results: list[dict]) -> str:
    if not results:
        return "No semantically relevant transaction records were retrieved."

    lines = []
    for i, item in enumerate(results, 1):
        meta = item.get("metadata") or {}
        distance = item.get("distance")

        merchant = meta.get("merchant", "Unknown merchant")
        date = meta.get("date", "")
        category = meta.get("category", "Other")
        amount = meta.get("amount", 0)
        txn_type = meta.get("transaction_type", "sent")

        distance_text = ""
        if isinstance(distance, (int, float)):
            distance_text = f"; similarity_distance={distance:.4f}"

        lines.append(
            f"{i}. {date} | {merchant} | Rs.{abs(float(amount or 0)):.2f} | "
            f"{txn_type} | {category}{distance_text}"
        )

    return "\n".join(lines)


# ── Main query ────────────────────────────────────────────────────────────────

def query(
    user_question: str,
    external_stats: dict = None,
    user_id: Any = None,
) -> dict:
    """
    Answer using:
      1. SQLite/structured analytics supplied by main.py
      2. User-isolated Chroma semantic retrieval
      3. Groq, with Ollama fallback

    Backward-compatible call:
        query(question, stats)

    Preferred call:
        query(question, stats, user_id=current_user_id)
    """
    stats = external_stats or {}

    if not stats:
        return {
            "answer": "No transaction data found. Upload a CSV first.",
            "sources": [],
            "provider": "none",
        }

    uid = _safe_user_id(user_id)
    retrieved = search_transactions(uid, user_question, n_results=8) if uid else []

    total_spent = float(stats.get("total_spent", 0) or 0)
    total_received = float(stats.get("total_received", 0) or 0)

    cat = stats.get("category_breakdown", {}) or {}
    cat_lines = "\n".join(
        f"  {name}: Rs.{float(amt or 0):.2f} "
        f"({round(float(amt or 0) / max(total_spent, 1) * 100)}%)"
        for name, amt in list(cat.items())[:8]
    ) or "  No category data"

    # Keep richer analytics if main.py already supplies them.
    top_merchants = stats.get("top_merchants", []) or []
    top_received_sources = stats.get("top_received_sources", []) or []
    monthly_trend = stats.get("monthly_trend", []) or []
    recurring_merchants = stats.get("recurring_merchants", []) or []
    largest_transactions = stats.get("largest_transactions", []) or []

    def _merchant_lines(items, limit=8):
        lines = []
        for item in items[:limit]:
            if isinstance(item, dict):
                name = item.get("merchant") or item.get("vendor") or item.get("name") or "Unknown"
                total = item.get("total", item.get("amount", 0))
                count = item.get("count", "")
                suffix = f", {count} transactions" if count != "" else ""
                lines.append(f"  {name}: Rs.{float(total or 0):.2f}{suffix}")
            else:
                lines.append(f"  {item}")
        return "\n".join(lines) or "  No data"

    def _monthly_lines(items, limit=12):
        lines = []
        for item in items[:limit]:
            if isinstance(item, dict):
                month = item.get("month") or item.get("date") or "Unknown"
                spent = item.get("spent", item.get("total_spent", item.get("amount", 0)))
                received = item.get("received", item.get("total_received", 0))
                lines.append(
                    f"  {month}: spent Rs.{float(spent or 0):.2f}, "
                    f"received Rs.{float(received or 0):.2f}"
                )
            else:
                lines.append(f"  {item}")
        return "\n".join(lines) or "  No monthly trend data"

    def _largest_lines(items, limit=8):
        lines = []
        for item in items[:limit]:
            if isinstance(item, dict):
                merchant = item.get("merchant") or item.get("vendor") or "Unknown"
                amount = item.get("amount", 0)
                date = item.get("date", "")
                lines.append(
                    f"  {date} | {merchant} | Rs.{float(amount or 0):.2f}"
                )
            else:
                lines.append(f"  {item}")
        return "\n".join(lines) or "  No largest-payment data"

    retrieved_context = _format_retrieved_context(retrieved)

    prompt = f"""You are a personal finance analyst for ONE authenticated user's UPI transaction history.
Answer the user's question directly in 3-5 concise sentences. Use Rs. for currency.

IMPORTANT PRIVACY RULE:
Use ONLY the transaction statistics and retrieved transaction records supplied below.
Never infer, invent, or mention transactions belonging to another user.
Merchant/vendor names and dates are intentionally preserved and may be used in the answer.
Do not expose masked sensitive identifiers.

STRUCTURED SPENDING SUMMARY:
- Total spent:    Rs.{total_spent:.2f}
- Total received: Rs.{total_received:.2f}
- Net flow:       Rs.{total_received - total_spent:.2f}
- Transactions:   {stats.get('total_transactions', stats.get('transaction_count', 0))}
- Largest single: Rs.{float(stats.get('highest_expense', 0) or 0):.2f}
- Date range:     {stats.get('date_range', 'Not available')}

By category:
{cat_lines}

Top merchants:
{_merchant_lines(top_merchants)}

Top received sources:
{_merchant_lines(top_received_sources)}

Monthly trend:
{_monthly_lines(monthly_trend)}

Recurring merchants:
{_merchant_lines(recurring_merchants)}

Largest payments:
{_largest_lines(largest_transactions)}

USER-ISOLATED SEMANTICALLY RELEVANT TRANSACTIONS:
{retrieved_context}

Question: {_mask(user_question)}
Answer:"""

    answer = _call_llm(prompt)
    provider = "groq" if GROQ_API_KEY else "ollama"

    sources = []
    for item in retrieved:
        meta = item.get("metadata") or {}
        sources.append(
            {
                "date": meta.get("date", ""),
                "merchant": meta.get("merchant", ""),
                "amount": meta.get("amount", 0),
                "category": meta.get("category", "Other"),
            }
        )

    return {
        "answer": answer,
        "sources": sources,
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
