"""Embedding provider adapters.

`fastembed`  - real local ONNX model (default; no API key, no per-call cost).
`hashing`    - deterministic test stub; refused in production by Settings.

Each provider exposes `space`, the identifier stored next to every vector.
Retrieval only compares a query vector with vectors of the same space.
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
from typing import Protocol

from app.core.config import Settings


class EmbeddingError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code = code


class EmbeddingProvider(Protocol):
    space: str
    dim: int
    price_per_mtok_usd: float

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedProvider:
    _lock = threading.Lock()
    _models: dict[str, object] = {}

    def __init__(self, settings: Settings):
        self.model_name = settings.embedding_model
        self.dim = settings.embedding_dim
        self.space = settings.embedding_space
        self.query_prefix = settings.embedding_query_prefix
        self.document_prefix = settings.embedding_document_prefix
        self.batch_size = settings.embedding_batch_size
        self.cache_dir = str(settings.model_cache_dir)
        self.price_per_mtok_usd = settings.embedding_price_per_mtok_usd

    def _model(self):
        with self._lock:
            if self.model_name not in self._models:
                try:
                    from fastembed import TextEmbedding
                except ImportError as exc:  # pragma: no cover
                    raise EmbeddingError("provider_unavailable", "install the 'local-embeddings' extra") from exc
                self._models[self.model_name] = TextEmbedding(model_name=self.model_name, cache_dir=self.cache_dir)
            return self._models[self.model_name]

    def _embed(self, texts: list[str]) -> list[list[float]]:
        vectors = [v.tolist() for v in self._model().embed(texts, batch_size=self.batch_size)]
        if vectors and len(vectors[0]) != self.dim:
            raise EmbeddingError("dimension_mismatch", f"model returned {len(vectors[0])}, EMBEDDING_DIM={self.dim}")
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed([self.document_prefix + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._embed([self.query_prefix + text])[0]


class HashingEmbeddingProvider:
    """Bag-of-words feature hashing. Deterministic, for tests only."""

    price_per_mtok_usd = 0.0

    def __init__(self, settings: Settings):
        self.dim = settings.embedding_dim
        self.space = settings.embedding_space

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in re.findall(r"\w+", text.lower()):
            h = int(hashlib.md5(tok[:6].encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def get_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "fastembed":
        return FastEmbedProvider(settings)
    if settings.embedding_provider == "hashing":
        return HashingEmbeddingProvider(settings)
    raise EmbeddingError("provider_unknown", settings.embedding_provider)
