import chromadb
from chromadb.utils import embedding_functions
import requests
from typing import Optional
import pandas as pd
import os
OLLAMA_BASE_URL = "http://localhost:11434"
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


def index_transactions(transactions: list[dict]) -> dict:
    col = _get_collection()
    if col.count() > 0:
        col.delete(ids=col.get()["ids"])

    docs, ids, metas = [], [], []
    for i, t in enumerate(transactions):
        amount   = float(t.get("amount", 0))
        merchant = t.get("merchant", "Unknown")
        date     = str(t.get("date", ""))
        txn_type = t.get("transaction_type", "sent")
        category = t.get("category", "General")
        cashback = float(t.get("cashback", 0))

        direction = "paid to" if txn_type == "sent" else "received from"
        doc = (
            f"Transaction {i+1}: Rs.{abs(amount):.2f} {direction} {merchant} "
            f"on {date}. Category: {category}. Cashback: Rs.{cashback:.2f}."
        )
        docs.append(doc)
        ids.append(f"txn_{i}")
        metas.append({
            "amount": amount, "merchant": merchant, "date": date,
            "transaction_type": txn_type, "category": category, "cashback": cashback,
        })

    col.add(documents=docs, ids=ids, metadatas=metas)
    return {"indexed": len(docs), "status": "ok"}


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
    top_merchants = (
        df[df["transaction_type"] == "sent"]
        .groupby("merchant")["amount"].apply(lambda x: x.abs().sum())
        .nlargest(5).to_dict()
    )
    return {
        "total_transactions": len(metas),
        "total_spent":        round(sent.sum(), 2),
        "total_received":     round(received.sum(), 2),
        "total_cashback":     round(df["cashback"].sum(), 2),
        "highest_expense":    round(sent.max(), 2) if not sent.empty else 0,
        "top_merchants":      {k: round(v, 2) for k, v in top_merchants.items()},
    }


def _call_claude(prompt: str) -> str:
    if not CLAUDE_API_KEY:
        return None
    try:
        resp = requests.post(
            CLAUDE_URL,
            headers={"x-api-key": CLAUDE_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": CLAUDE_MODEL, "max_tokens": 512, "messages": [{"role": "user", "content": prompt}]},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]
    except Exception as e:
        print(f"Claude API error: {e}")
        return None


def _call_ollama(prompt: str) -> str:
    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("response", "No response from model.")
    except requests.exceptions.ConnectionError:
        return f"Ollama not running. Run: ollama serve && ollama pull {OLLAMA_MODEL}"
    except Exception as e:
        return f"Ollama error: {str(e)}"


def query(user_question: str) -> dict:
    col = _get_collection()
    if col.count() == 0:
        return {"answer": "No transactions indexed yet. Upload a PDF/CSV first.", "sources": []}

    hits  = retrieve(user_question, n_results=8)
    stats = _compute_stats()

    prompt = f"""You are a UPI transaction analyst. Answer using ONLY the data below. Use Rs. for amounts.

Stats: {stats['total_transactions']} transactions, Rs.{stats['total_spent']} spent, Rs.{stats['total_received']} received.

Relevant transactions:
{chr(10).join(f"- {h['document']}" for h in hits)}

Question: {user_question}
Answer:"""

    return {
        "answer":  _call_ollama(prompt),
        "sources": [h["document"] for h in hits[:3]],
        "stats":   stats,
    }


def ollama_status() -> dict:
    try:
        resp   = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        models = [m["name"] for m in resp.json().get("models", [])]
        return {"running": True, "models": models, "active_model": OLLAMA_MODEL}
    except Exception:
        return {"running": False, "models": [], "active_model": OLLAMA_MODEL}
