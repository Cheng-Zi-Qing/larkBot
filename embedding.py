"""Embedding service — opt-in semantic search via Jina/OpenAI-compatible API.

Disabled when EMBEDDING_API_KEY is empty. All functions gracefully return None/[].
"""
from __future__ import annotations

import json
import struct
import threading
from typing import Any

import config

_lock = threading.Lock()
_session = None


def enabled() -> bool:
    return bool(config.EMBEDDING_API_KEY)


def _get_session():
    global _session
    if _session is not None:
        return _session
    import httpx
    _session = httpx.Client(timeout=30.0)
    return _session


def get_embedding(text: str) -> bytes | None:
    """Get embedding vector for text. Returns packed float32 bytes or None."""
    if not enabled():
        return None
    if not text.strip():
        return None

    try:
        client = _get_session()
        resp = client.post(
            config.EMBEDDING_BASE_URL,
            headers={
                "Authorization": f"Bearer {config.EMBEDDING_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.EMBEDDING_MODEL,
                "input": [text[:2000]],
                "dimensions": config.EMBEDDING_DIM,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        vec = data["data"][0]["embedding"]
        return _pack_vector(vec)
    except Exception:
        return None


def get_embeddings_batch(texts: list[str]) -> list[bytes | None]:
    """Get embeddings for multiple texts in one API call."""
    if not enabled() or not texts:
        return [None] * len(texts)

    try:
        client = _get_session()
        resp = client.post(
            config.EMBEDDING_BASE_URL,
            headers={
                "Authorization": f"Bearer {config.EMBEDDING_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.EMBEDDING_MODEL,
                "input": [t[:2000] for t in texts],
                "dimensions": config.EMBEDDING_DIM,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        results = [None] * len(texts)
        for item in data["data"]:
            idx = item["index"]
            results[idx] = _pack_vector(item["embedding"])
        return results
    except Exception:
        return [None] * len(texts)


def cosine_similarity(a: bytes, b: bytes) -> float:
    """Compute cosine similarity between two packed vectors."""
    va = _unpack_vector(a)
    vb = _unpack_vector(b)
    dot = sum(x * y for x, y in zip(va, vb))
    norm_a = sum(x * x for x in va) ** 0.5
    norm_b = sum(x * x for x in vb) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def search_by_embedding(
    query_vec: bytes, candidates: list[tuple[Any, bytes]], top_k: int = 5,
) -> list[tuple[Any, float]]:
    """Rank candidates by cosine similarity to query_vec.

    candidates: list of (id, packed_embedding) tuples.
    Returns: list of (id, score) sorted by score descending.
    """
    scored = []
    for item_id, vec_bytes in candidates:
        if vec_bytes:
            score = cosine_similarity(query_vec, vec_bytes)
            scored.append((item_id, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def _pack_vector(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack_vector(data: bytes) -> list[float]:
    n = len(data) // 4
    return list(struct.unpack(f"{n}f", data))
