"""Optional cross-encoder reranking of the fused candidate pool.

Off by default (RETRIEVAL_RERANKER=""). Enabled only when the dev retrieval
eval shows it helps; see docs/evaluation.md. Uses a local ONNX model through
fastembed, so there is no API call and no per-query cost.
"""

from __future__ import annotations

import threading

from app.core.config import Settings

_lock = threading.Lock()
_models: dict[str, object] = {}


def _model(name: str, cache_dir: str):
    with _lock:
        if name not in _models:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            _models[name] = TextCrossEncoder(model_name=name, cache_dir=cache_dir)
        return _models[name]


def rerank(settings: Settings, question: str, passages: list[str]) -> list[float]:
    """Relevance score per passage (higher = more relevant)."""
    if not passages:
        return []
    model = _model(settings.retrieval_reranker, str(settings.model_cache_dir))
    return [float(x) for x in model.rerank(question, passages, batch_size=8)]
