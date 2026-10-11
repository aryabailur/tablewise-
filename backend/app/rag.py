"""RAG over the per-restaurant knowledge base: markdown -> heading chunks -> fastembed -> ChromaDB.

Layout: knowledge/<restaurant_slug>/{about,menu,policies}.md plus knowledge/_platform/faq.md.
Each chunk carries restaurant_slug metadata ("_platform" for Tablewise-wide docs) and is mirrored into the
rag_documents SQL table.
"""
from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import chromadb

BASE_DIR = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
CHROMA_DIR = Path(os.getenv("CHROMA_DIR") or BASE_DIR / "data" / "chroma")
MODEL_CACHE = Path(os.getenv("FASTEMBED_CACHE_DIR") or BASE_DIR / "data" / "fastembed_cache")
COLLECTION = "tablewise_knowledge"
PLATFORM_SLUG = "_platform"
DOC_NAMES = ("about", "menu", "policies")
EMBED_MODEL = "BAAI/bge-small-en-v1.5"

CHUNK_TOKENS = 400
OVERLAP_TOKENS = 50
WORDS_PER_TOKEN = 0.75  # rough English heuristic: ~0.75 words per token

_lock = threading.Lock()
_embedder = None
_client = None


def _get_embedder():
    global _embedder
    with _lock:
        if _embedder is None:
            from fastembed import TextEmbedding
            MODEL_CACHE.mkdir(parents=True, exist_ok=True)
            _embedder = TextEmbedding(model_name=EMBED_MODEL, cache_dir=str(MODEL_CACHE))
        return _embedder


def _get_client():
    global _client
    if _client is None:
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return _client


def _collection(create: bool = True):
    client = _get_client()
    if create:
        return client.get_or_create_collection(COLLECTION, embedding_function=None, metadata={"hnsw:space": "cosine"})
    return client.get_collection(COLLECTION, embedding_function=None)


# ---------------------------------------------------------------- chunking

def chunk_markdown(text: str, source: str) -> list[dict[str, Any]]:
    """Split by headings, then window long sections to ~400 tokens with 50 token overlap."""
    sections: list[tuple[str, list[str]]] = []
    h1, title, buf = "", "", []
    for line in text.splitlines():
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            if buf and any(l.strip() for l in buf):
                sections.append((title or h1, buf))
            level, heading = len(m.group(1)), m.group(2).strip()
            if level == 1:
                h1, title = heading, heading
            else:
                title = heading
            buf = []
        else:
            buf.append(line)
    if buf and any(l.strip() for l in buf):
        sections.append((title or h1, buf))

    max_words = int(CHUNK_TOKENS * WORDS_PER_TOKEN)
    overlap_words = int(OVERLAP_TOKENS * WORDS_PER_TOKEN)
    chunks = []
    for section, lines in sections:
        body = "\n".join(lines).strip()
        words = body.split(" ")
        start = 0
        while start < len(words):
            piece = " ".join(words[start:start + max_words]).strip()
            header = f"{h1} — {section}" if section != h1 else h1
            chunks.append({"text": f"{header}\n\n{piece}", "source": source, "section": section})
            if start + max_words >= len(words):
                break
            start += max_words - overlap_words
    return chunks


# ---------------------------------------------------------------- ingest / retrieve

def load_chunks(knowledge_dir: Path = KNOWLEDGE_DIR) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for folder in sorted(p for p in knowledge_dir.iterdir() if p.is_dir()):
        for path in sorted(folder.glob("*.md")):
            file_chunks = chunk_markdown(path.read_text(encoding="utf-8"), path.name)
            for i, c in enumerate(file_chunks):
                c.update(restaurant_slug=folder.name, chunk_index=i, id=f"{folder.name}/{path.name}::{i}")
            chunks.extend(file_chunks)
    return chunks


def _store_sql(chunks: list[dict[str, Any]]) -> None:
    from sqlmodel import delete

    from .db import RagDocument, get_session, init_db
    init_db()
    with get_session() as s:
        s.exec(delete(RagDocument))
        for c in chunks:
            s.add(RagDocument(id=c["id"], restaurant_slug=c["restaurant_slug"], source=c["source"],
                              section=c["section"], chunk_index=c["chunk_index"], text=c["text"]))
        s.commit()


def ingest(knowledge_dir: Path = KNOWLEDGE_DIR) -> int:
    """Idempotent: drops and rebuilds the collection (and rag_documents table) from every <slug>/*.md file."""
    chunks = load_chunks(knowledge_dir)
    client = _get_client()
    try:
        client.delete_collection(COLLECTION)
    except Exception:
        pass
    col = _collection()
    _store_sql(chunks)
    if not chunks:
        return 0
    embeddings = [e.tolist() for e in _get_embedder().embed([c["text"] for c in chunks])]
    col.add(
        ids=[c["id"] for c in chunks],
        documents=[c["text"] for c in chunks],
        metadatas=[{"source": c["source"], "section": c["section"], "restaurant_slug": c["restaurant_slug"],
                    "chunk_index": c["chunk_index"]} for c in chunks],
        embeddings=embeddings,
    )
    return len(chunks)


def count() -> int:
    try:
        return _collection(create=False).count()
    except Exception:
        return 0


def read_docs(restaurant_slug: str, knowledge_dir: Path = KNOWLEDGE_DIR) -> dict[str, str]:
    """Raw markdown for a restaurant page: {"about": md, "menu": md, "policies": md} ("" when missing)."""
    folder = knowledge_dir / restaurant_slug
    out = {}
    for name in DOC_NAMES:
        path = folder / f"{name}.md"
        out[name] = path.read_text(encoding="utf-8") if path.is_file() else ""
    return out


def retrieve(query: str, k: int = 4, restaurant_slug: str | None = None) -> list[dict[str, Any]]:
    """Top-k chunks. With restaurant_slug, only that restaurant's docs plus the platform FAQ are searched."""
    from . import metrics
    started = time.perf_counter()
    try:
        if count() == 0:
            ingest()
        q = next(iter(_get_embedder().query_embed(query))).tolist()
        kwargs: dict[str, Any] = {}
        if restaurant_slug:
            kwargs["where"] = {"restaurant_slug": {"$in": [restaurant_slug, PLATFORM_SLUG]}}
        res = _collection().query(query_embeddings=[q], n_results=k, include=["documents", "metadatas", "distances"],
                                  **kwargs)
    finally:
        metrics.RAG_RETRIEVAL.observe(time.perf_counter() - started)
    out = []
    for i, (doc, meta, dist) in enumerate(zip(res["documents"][0], res["metadatas"][0], res["distances"][0]), start=1):
        out.append({"index": i, "source": meta.get("source"), "section": meta.get("section"),
                    "restaurant_slug": meta.get("restaurant_slug"), "text": doc, "score": round(1 - float(dist), 3)})
    return out
