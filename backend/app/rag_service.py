"""
RAG service.
  retrieval : per-user ChromaDB collection (ONNX all-MiniLM-L6-v2 embeddings, no torch)
              with an automatic keyword fallback when the vector stack is unavailable
              or the server is low on memory.
  generation: Groq (models discovered at runtime) -> local Ollama fallback.
  privacy   : account numbers, UPI IDs, phone numbers and long reference IDs are masked
              before anything is sent to the LLM.
"""
import os, re, time, hashlib, threading
from typing import Optional, List, Dict, Tuple
import requests

GROQ_BASE = "https://api.groq.com/openai/v1"
PREFERRED_MODELS = ["openai/gpt-oss-20b", "openai/gpt-oss-120b",
                    "llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
SKIP_MODEL_WORDS = ("whisper", "tts", "guard", "orpheus", "playai", "embed", "distil-whisper")

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "deepseek-r1:8b")

SYSTEM = ("You are a careful personal-finance analyst for a UPI transaction dashboard. "
          "Answer ONLY from the data provided. Use Rs. for amounts. Be specific: name merchants, "
          "months and amounts. If the data does not contain the answer, say so. Max 6 sentences.")

# ── masking ───────────────────────────────────────────────────────────────────
_MASKS = [
    (re.compile(r'\b[X*x]{2,}\d{3,4}\b'), '[ACCT]'),
    (re.compile(r'\b[\w.\-]+@[a-zA-Z]{2,}\b'), '[UPI]'),
    (re.compile(r'\b[6-9]\d{9}\b'), '[PHONE]'),
    (re.compile(r'\b\d{11,}\b'), '[ID]'),
    (re.compile(r'\b[A-Z]{5}\d{4}[A-Z]\b'), '[PAN]'),
]

def mask(text: str) -> str:
    for pat, rep in _MASKS:
        text = pat.sub(rep, text or "")
    return text


# ── Groq ──────────────────────────────────────────────────────────────────────
def _key() -> str:
    return os.getenv("GROQ_API_KEY", "").strip().strip('"').strip("'")

_mcache = {"t": 0.0, "ids": [], "err": None}

def _groq_models(force: bool = False) -> Tuple[List[str], Optional[str]]:
    key = _key()
    if not key:
        return [], "GROQ_API_KEY is not set on the server"
    if not force and time.time() - _mcache["t"] < 600 and (_mcache["ids"] or _mcache["err"]):
        return _mcache["ids"], _mcache["err"]
    ids, err = [], None
    try:
        r = requests.get(f"{GROQ_BASE}/models", headers={"Authorization": f"Bearer {key}"}, timeout=8)
        if r.status_code == 200:
            ids = [m["id"] for m in r.json().get("data", []) if m.get("active", True)]
            if not ids:
                err = "Groq returned no models"
        elif r.status_code in (401, 403):
            err = "Groq rejected the API key (check GROQ_API_KEY)"
        else:
            err = f"Groq HTTP {r.status_code}"
    except Exception as e:
        err = f"Cannot reach Groq: {type(e).__name__}"
    _mcache.update(t=time.time(), ids=ids, err=err)
    return ids, err

def _pick_model(ids: List[str]) -> Optional[str]:
    want = os.getenv("GROQ_MODEL", "").strip()
    if want and want in ids:
        return want
    for m in PREFERRED_MODELS:
        if m in ids:
            return m
    usable = [i for i in ids if not any(w in i.lower() for w in SKIP_MODEL_WORDS)]
    return usable[0] if usable else None

def _clean(text: str) -> str:
    return re.sub(r'<think>.*?</think>', '', text or '', flags=re.S).strip()

def _groq_chat(prompt: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """returns (text, error, model)"""
    ids, err = _groq_models()
    if not ids:
        return None, err, None
    model = _pick_model(ids)
    if not model:
        return None, "No usable chat model available on this Groq key", None
    body = {"model": model, "temperature": 0.3, "max_tokens": 1500,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}
    if model.startswith("openai/gpt-oss"):
        body["reasoning_effort"] = "low"
    try:
        r = requests.post(f"{GROQ_BASE}/chat/completions",
                          headers={"Authorization": f"Bearer {_key()}"}, json=body, timeout=45)
        if r.status_code == 200:
            msg = r.json()["choices"][0]["message"]
            text = _clean(msg.get("content") or "")
            return (text, None, model) if text else (None, "Model returned an empty answer", model)
        if r.status_code in (400, 404):
            _mcache["t"] = 0  # force re-discovery next time (model may have been retired)
        try:
            detail = r.json().get("error", {}).get("message", r.text[:200])
        except Exception:
            detail = r.text[:200]
        return None, f"Groq error {r.status_code}: {detail}", model
    except requests.Timeout:
        return None, "Groq timed out, try again", model
    except Exception as e:
        return None, f"Groq request failed: {type(e).__name__}", model

def _ollama_chat(prompt: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        r = requests.post(f"{OLLAMA_URL}/api/generate", timeout=60,
                          json={"model": OLLAMA_MODEL, "prompt": SYSTEM + "\n\n" + prompt, "stream": False})
        r.raise_for_status()
        t = _clean(r.json().get("response", ""))
        return (t, None) if t else (None, "Ollama returned nothing")
    except Exception:
        return None, "Local Ollama is not running"


# ── vector store (lazy, optional) ─────────────────────────────────────────────
_client = None
_ef = None
_state: Dict[str, dict] = {}      # uid -> {status, count, fp, error}
_lock = threading.Lock()

def _headroom_mb() -> Optional[float]:
    try:
        with open("/sys/fs/cgroup/memory.max") as f:
            mx = f.read().strip()
        with open("/sys/fs/cgroup/memory.current") as f:
            cur = int(f.read().strip())
        if mx != "max":
            return (int(mx) - cur) / 1048576
    except Exception:
        pass
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable"):
                    return int(line.split()[1]) / 1024
    except Exception:
        pass
    return None

def vector_allowed() -> Tuple[bool, str]:
    if os.getenv("RAG_VECTOR", "1") == "0":
        return False, "disabled by RAG_VECTOR=0"
    if _client is None:
        room = _headroom_mb()
        if room is not None and room < 300:
            return False, f"low memory ({room:.0f} MB free)"
    return True, ""

def _get_client():
    global _client, _ef
    if _client is None:
        import chromadb
        from chromadb.config import Settings
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
        _client = chromadb.PersistentClient(path=os.getenv("CHROMA_PATH", "./chroma_db"),
                                            settings=Settings(anonymized_telemetry=False))
        _ef = DefaultEmbeddingFunction()   # ONNX all-MiniLM-L6-v2, 384-dim
    return _client, _ef

def _col(uid: str):
    client, ef = _get_client()
    return client.get_or_create_collection(name=f"user_{uid}", embedding_function=ef,
                                           metadata={"hnsw:space": "cosine"})

def _fingerprint(docs: List[dict]) -> str:
    h = hashlib.md5()
    for d in docs:
        h.update(d["text"].encode())
    return h.hexdigest()

def _index_worker(uid: str, docs: List[dict], fp: str):
    try:
        client, _ = _get_client()
        try:
            client.delete_collection(f"user_{uid}")
        except Exception:
            pass
        col = _col(uid)
        for i in range(0, len(docs), 200):
            chunk = docs[i:i + 200]
            col.add(ids=[d["id"] for d in chunk], documents=[d["text"] for d in chunk],
                    metadatas=[d["meta"] for d in chunk])
        _state[uid] = {"status": "ready", "count": len(docs), "fp": fp, "error": None}
        print(f"[rag] indexed {len(docs)} docs for user {uid}")
    except Exception as e:
        _state[uid] = {"status": "error", "count": 0, "fp": None, "error": f"{type(e).__name__}: {e}"[:200]}
        print(f"[rag] index failed for user {uid}: {e}")

def ensure_index(uid: str, docs: List[dict], wait: bool = False) -> str:
    """Start (re)indexing in the background if the docs changed. Returns state status."""
    uid = str(uid)
    ok, why = vector_allowed()
    if not ok:
        _state[uid] = {"status": "keyword", "count": 0, "fp": None, "error": why}
        return "keyword"
    fp = _fingerprint(docs)
    with _lock:
        st = _state.get(uid)
        if st and st["fp"] == fp and st["status"] in ("ready", "indexing"):
            return st["status"]
        _state[uid] = {"status": "indexing", "count": 0, "fp": fp, "error": None}
        t = threading.Thread(target=_index_worker, args=(uid, docs, fp), daemon=True)
        t.start()
    if wait:
        t.join(timeout=120)
    return _state[uid]["status"]

def index_state(uid: str) -> dict:
    return _state.get(str(uid), {"status": "none", "count": 0, "error": None})


# ── retrieval ─────────────────────────────────────────────────────────────────
_STOP = set("the a an of in on at to for and or is are was were my me i how much what which who when did do does "
            "spend spent paid pay total all any from with about this that it by be have has had show tell give "
            "last month months year more most less".split())
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

def _keyword_hits(question: str, docs: List[dict], n: int) -> List[dict]:
    q = question.lower()
    toks = [t for t in re.findall(r"[a-z0-9]+", q) if t not in _STOP and len(t) > 1]
    months = {v for k, v in _MONTHS.items() if re.search(rf"\b{k}", q)}
    scored = []
    for d in docs:
        txt = d["text"].lower()
        s = sum(2 for t in toks if t in txt)
        if months and int(d["meta"].get("month", "0-0").split("-")[1] or 0) in months:
            s += 3
        if s:
            scored.append((s, d))
    scored.sort(key=lambda x: -x[0])
    return [d for _, d in scored[:n]]

def retrieve(uid: str, question: str, docs: List[dict], n: int = 12) -> Tuple[List[dict], str]:
    uid = str(uid)
    st = _state.get(uid, {})
    if st.get("status") == "ready":
        try:
            res = _col(uid).query(query_texts=[question], n_results=min(n, max(1, st["count"])))
            hits = [{"text": t, "meta": m} for t, m in zip(res["documents"][0], res["metadatas"][0])]
            if hits:
                return hits, "vector"
        except Exception as e:
            print(f"[rag] vector query failed, using keyword: {e}")
    return _keyword_hits(question, docs, n), "keyword"


# ── public api ────────────────────────────────────────────────────────────────
def build_docs(rows: List[dict]) -> List[dict]:
    docs = []
    for i, t in enumerate(rows):
        date = str(t["date"])[:10]
        kind = "paid to" if t["transaction_type"] == "sent" else "received from"
        text = f"{date}: Rs.{abs(float(t['amount'])):.0f} {kind} {mask(str(t['merchant']))} ({t['category']})"
        docs.append({"id": f"t{t.get('id', i)}", "text": text,
                     "meta": {"month": date[:7], "category": str(t["category"]),
                              "type": str(t["transaction_type"]), "amount": float(t["amount"])}})
    return docs

def query(question: str, user_id, stats: dict, docs: List[dict]) -> dict:
    uid = str(user_id)
    ensure_index(uid, docs)            # non-blocking; keyword retrieval covers until ready
    hits, mode = retrieve(uid, question, docs)

    spent, recv = stats.get("total_spent", 0), stats.get("total_received", 0)
    def lines(items, fmt):
        return "\n".join(fmt(x) for x in items) or "  none"
    cat = "\n".join(f"  {k}: Rs.{v:.0f} ({v / max(spent, 1) * 100:.0f}%)"
                    for k, v in sorted(stats.get("category_breakdown", {}).items(), key=lambda x: -x[1])[:10]) or "  none"
    monthly = "\n".join(f"  {x['month']}: spent Rs.{x['spent']:.0f}, received Rs.{x['received']:.0f}"
                        for x in stats.get("monthly_combined", [])[-8:]) or "  none"
    prompt = f"""PERIOD: {stats.get('date_range') or 'all data'}
TOTAL SPENT: Rs.{spent:.0f} | TOTAL RECEIVED: Rs.{recv:.0f} | NET: Rs.{recv - spent:.0f}
SPENDING TRANSACTIONS: {stats.get('transaction_count', 0)} | RECEIVED: {stats.get('received_count', 0)}

SPENDING BY CATEGORY:
{cat}

MONTHLY:
{monthly}

TOP MERCHANTS:
{lines(stats.get('top_merchants', [])[:6], lambda m: f"  {mask(m['name'])}: Rs.{m['spent']:.0f} ({m['count']}x)")}

INCOME SOURCES:
{lines(stats.get('top_received_sources', [])[:4], lambda m: f"  {mask(m['name'])}: Rs.{m['received']:.0f} ({m['count']}x)")}

RECURRING:
{lines(stats.get('recurring_merchants', [])[:4], lambda r: f"  {mask(r['merchant'])}: {r['count']}x, avg Rs.{r['avg']:.0f}")}

MOST RELEVANT TRANSACTIONS ({mode} search):
{lines(hits, lambda h: '  ' + h['text'])}

QUESTION: {mask(question)}
ANSWER:"""

    text, err, model = _groq_chat(prompt)
    provider = "groq"
    if not text and not _key():
        text, err = _ollama_chat(prompt)
        provider, model = "ollama", OLLAMA_MODEL
    if not text:
        return {"answer": f"AI is unavailable right now. {err or ''}".strip(), "error": err,
                "provider": provider, "model": model, "retrieval": mode, "sources": []}
    return {"answer": text, "provider": provider, "model": model, "retrieval": mode,
            "sources": [h["text"] for h in hits[:3]]}

def ai_status() -> dict:
    if _key():
        ids, err = _groq_models()
        model = _pick_model(ids) if ids else None
        return {"running": bool(model), "provider": "groq", "model": model, "error": err}
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        models = [m["name"] for m in r.json().get("models", [])]
        return {"running": bool(models), "provider": "ollama", "model": OLLAMA_MODEL,
                "error": None if models else "No Ollama models installed"}
    except Exception:
        return {"running": False, "provider": "none", "model": None,
                "error": "Set GROQ_API_KEY on the server (or run Ollama locally)"}
