#!/usr/bin/env python3
"""Opportunity clustering helpers.

Provides lightweight text embeddings with API-first behavior and a deterministic
hashing fallback, then groups opportunities into clusters.
"""

from __future__ import annotations

import hashlib
import math
import os
import random
import re
from collections import Counter
from typing import Any

import requests


EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 128
DEFAULT_TIMEOUT_SECONDS = 20
_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]{1,}")
_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "are",
    "was",
    "were",
    "been",
    "have",
    "has",
    "had",
    "into",
    "onto",
    "over",
    "under",
    "out",
    "about",
    "within",
    "across",
    "your",
    "their",
    "its",
    "our",
    "will",
    "can",
    "could",
    "should",
    "would",
    "more",
    "most",
    "than",
    "then",
    "them",
    "they",
    "you",
    "not",
    "all",
    "any",
    "one",
    "two",
    "new",
    "use",
    "using",
    "based",
}


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text or "")]


def _hashing_embedding(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    vector = [0.0] * dim
    tokens = _tokenize(text)
    if not tokens:
        return vector

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign

    norm = math.sqrt(sum(value * value for value in vector))
    if norm > 0:
        vector = [value / norm for value in vector]
    return vector


def embed_text(text: str) -> list[float]:
    """Embed text with OpenAI embeddings API and hash fallback on failure."""
    api_key = (os.environ.get("AI_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return _hashing_embedding(text)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"model": EMBEDDING_MODEL, "input": text or ""}

    try:
        response = requests.post(
            "https://api.openai.com/v1/embeddings",
            headers=headers,
            json=payload,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        vector = data.get("data", [{}])[0].get("embedding")
        if not isinstance(vector, list) or not vector:
            raise ValueError("Invalid embedding response")
        return [float(value) for value in vector]
    except Exception:
        return _hashing_embedding(text)


def _combine_text(opp: dict[str, Any]) -> str:
    title = str(opp.get("title") or opp.get("name") or "")
    description = str(opp.get("description") or opp.get("details") or "")
    summary = str(opp.get("summary") or "")
    return "\n".join(part for part in [title, description, summary] if part).strip()


def _l2_distance(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) * (x - y) for x, y in zip(a, b)))


def _mean_vector(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    dim = len(vectors[0])
    if dim == 0:
        return []
    avg = [0.0] * dim
    for vector in vectors:
        for idx in range(dim):
            avg[idx] += vector[idx]
    count = float(len(vectors))
    return [value / count for value in avg]


def _run_kmeans(vectors: list[list[float]], k: int, max_iters: int = 20) -> list[int]:
    if not vectors:
        return []

    n = len(vectors)
    k = max(1, min(k, n))

    rng = random.Random(42)
    initial_indices = list(range(n))
    rng.shuffle(initial_indices)
    centroids = [vectors[idx][:] for idx in initial_indices[:k]]
    assignments = [0] * n

    for _ in range(max_iters):
        changed = False

        for idx, vector in enumerate(vectors):
            best_cluster = min(range(k), key=lambda cluster_idx: _l2_distance(vector, centroids[cluster_idx]))
            if assignments[idx] != best_cluster:
                assignments[idx] = best_cluster
                changed = True

        grouped: list[list[list[float]]] = [[] for _ in range(k)]
        for idx, cluster_idx in enumerate(assignments):
            grouped[cluster_idx].append(vectors[idx])

        for cluster_idx in range(k):
            if grouped[cluster_idx]:
                centroids[cluster_idx] = _mean_vector(grouped[cluster_idx])

        if not changed:
            break

    return assignments


def _cluster_keywords(texts: list[str], max_keywords: int = 5) -> list[str]:
    counter: Counter[str] = Counter()
    for text in texts:
        for token in _tokenize(text):
            if token in _STOPWORDS or len(token) < 3:
                continue
            counter[token] += 1
    return [token for token, _ in counter.most_common(max_keywords)]


def cluster_opportunities(opps: list[dict[str, Any]], num_clusters: int = 5) -> dict[str, Any]:
    """Cluster opportunities and return cluster payload with labels.

    Returns:
        {"clusters": [{"id": int, "label": str, "opportunities": [...]}, ...]}
    """
    valid_opps = [opp for opp in opps if isinstance(opp, dict)]
    if not valid_opps:
        return {"clusters": []}

    texts = [_combine_text(opp) for opp in valid_opps]
    vectors = [embed_text(text) for text in texts]
    assignments = _run_kmeans(vectors, num_clusters)

    grouped_indices: dict[int, list[int]] = {}
    for idx, cluster_id in enumerate(assignments):
        grouped_indices.setdefault(cluster_id, []).append(idx)

    clusters: list[dict[str, Any]] = []
    for cluster_id in sorted(grouped_indices.keys()):
        member_indices = grouped_indices[cluster_id]
        cluster_texts = [texts[idx] for idx in member_indices]
        keywords = _cluster_keywords(cluster_texts)
        label = ", ".join(keywords[:4]) if keywords else f"Cluster {cluster_id}"

        opportunities: list[dict[str, Any]] = []
        for idx in member_indices:
            enriched = dict(valid_opps[idx])
            enriched["cluster_id"] = cluster_id
            enriched["cluster_label"] = label
            opportunities.append(enriched)

        opportunities.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
        clusters.append({"id": cluster_id, "label": label, "opportunities": opportunities})

    return {"clusters": clusters}
