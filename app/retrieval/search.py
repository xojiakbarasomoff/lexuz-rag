"""Hybrid retrieval over the *active* versions only.

1. normalize the question (original kept; Latin variant added for Cyrillic input)
2. semantic search: query vector vs chunk vectors of the same embedding space
3. lexical search: PostgreSQL 'simple' FTS with prefix terms + explicit
   article-number matches ("12-modda", "12¹-modda")
4. Reciprocal Rank Fusion over all ranked lists:  score = Σ 1 / (k + rank)
5. deduplicate by article (best chunk wins, other matched chunks are kept)
6. build a bounded context: whole article when it fits, otherwise the matched
   chunks and their direct neighbours, under a hard token budget.

Scores are rank-fusion numbers, not probabilities, and are never shown to users
as "confidence".
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.ingestion.chunker import estimate_tokens
from app.providers.embeddings import EmbeddingProvider
from app.retrieval.normalize import STOPWORDS, normalize_for_search, query_stem, query_variants

_ARTICLE_REF_RE = re.compile(r"(\d{1,4})\s*([¹²³⁴⁵⁶⁷⁸⁹]|[-.^]\s*(\d))?\s*[-–]?\s*modd", re.I)
_TO_SUP = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
PER_ARTICLE_TOKEN_CAP = 1800


@dataclass
class Candidate:
    chunk_id: uuid.UUID
    article_id: uuid.UUID
    ordinal: int


@dataclass
class RetrievedArticle:
    article_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    version_id: uuid.UUID
    label: str
    title: str
    heading_context: str
    full_text: str
    context_text: str
    source_url: str
    checked_at: datetime | None
    future_effective: bool
    score: float
    matched_chunk_ids: list[uuid.UUID] = field(default_factory=list)
    source_id: str = ""


@dataclass
class RetrievalResult:
    articles: list[RetrievedArticle]
    ranked_article_ids: list[uuid.UUID]  # full fused ranking (for evaluation)
    embedding_space: str
    query_tokens_est: int


def article_refs(question: str) -> list[str]:
    """Article labels explicitly mentioned in the question."""
    out = []
    for m in _ARTICLE_REF_RE.finditer(question):
        base = m.group(1)
        sup = m.group(2) or ""
        if m.group(3):
            sup = m.group(3).translate(_TO_SUP)
        elif sup and sup[0] not in "¹²³⁴⁵⁶⁷⁸⁹":
            sup = ""
        out.append(base + sup)
    return out


def build_tsquery(question: str) -> str | None:
    terms = []
    for tok in normalize_for_search(question).split():
        if tok in STOPWORDS or len(tok) < 3 or tok.isdigit():
            continue
        stem = query_stem(tok)
        if stem and stem not in terms:
            terms.append(stem)
    if not terms:
        return None
    return " | ".join(f"{t}:*" for t in terms[:16])


_ACTIVE_FILTER = """
    FROM chunks c
    JOIN documents d ON d.active_version_id = c.version_id
    JOIN articles a ON a.id = c.article_id AND a.status = 'in_force'
    WHERE (CAST(:doc_ids AS uuid[]) IS NULL OR d.id = ANY(CAST(:doc_ids AS uuid[])))
"""


def semantic_search(s: Session, qvec: list[float], space: str, doc_ids, limit: int) -> list[Candidate]:
    sql = text(
        "SELECT c.id, c.article_id, c.ordinal "
        + _ACTIVE_FILTER.replace(
            "WHERE",
            "JOIN chunk_embeddings ce ON ce.content_hash = c.content_hash AND ce.embedding_space = :space WHERE",
        )
        + " ORDER BY ce.embedding <=> CAST(:qvec AS vector) LIMIT :limit"
    )
    rows = s.execute(sql, {"qvec": str(qvec), "space": space, "doc_ids": doc_ids, "limit": limit}).all()
    return [Candidate(r[0], r[1], r[2]) for r in rows]


def article_ref_search(s: Session, question: str, doc_ids, limit: int) -> list[Candidate]:
    """Chunks of articles whose number is written in the question ("130-modda")."""
    refs = article_refs(question)
    if not refs:
        return []
    sql = text(
        "SELECT c.id, c.article_id, c.ordinal "
        + _ACTIVE_FILTER
        + " AND a.label IN :labels ORDER BY a.ordinal, c.ordinal LIMIT :limit"
    ).bindparams(bindparam("labels", expanding=True))
    return [Candidate(*r) for r in s.execute(sql, {"labels": refs, "doc_ids": doc_ids, "limit": limit})]


def lexical_search(s: Session, question: str, doc_ids, limit: int) -> list[Candidate]:
    """PostgreSQL full-text search ('simple' config, prefix terms)."""
    tsq = build_tsquery(question)
    if not tsq:
        return []
    sql = text(
        "SELECT c.id, c.article_id, c.ordinal, ts_rank_cd(c.tsv, q, 1) AS rank "
        + _ACTIVE_FILTER.replace("WHERE", ", to_tsquery('simple', :tsq) q WHERE")
        + " AND c.tsv @@ q ORDER BY rank DESC LIMIT :limit"
    )
    return [Candidate(r[0], r[1], r[2]) for r in s.execute(sql, {"tsq": tsq, "doc_ids": doc_ids, "limit": limit})]


_APOS_CHARS = "ʻʼ'‘’`´"


def title_search(s: Session, question: str, doc_ids, limit: int) -> list[Candidate]:
    """Lexical match against article titles only.

    Article titles in Uzbek codes are short, precise summaries of the rule, so a
    title hit is strong evidence. Returns the article's first chunk as the
    representative candidate.
    """
    tsq = build_tsquery(question)
    if not tsq:
        return []
    sql = text(
        "SELECT c.id, c.article_id, c.ordinal, "
        "ts_rank_cd(to_tsvector('simple', translate(lower(a.title), :apos, '')), q, 1) AS rank "
        + _ACTIVE_FILTER.replace("WHERE", ", to_tsquery('simple', :tsq) q WHERE")
        + " AND c.ordinal = 0 AND to_tsvector('simple', translate(lower(a.title), :apos, '')) @@ q"
        " ORDER BY rank DESC, a.ordinal LIMIT :limit"
    )
    rows = s.execute(sql, {"tsq": tsq, "apos": _APOS_CHARS, "doc_ids": doc_ids, "limit": limit})
    return [Candidate(r[0], r[1], r[2]) for r in rows]


def rrf_fuse(
    ranked_lists: list[list[Candidate]], k: int, weights: list[float] | None = None
) -> tuple[dict[uuid.UUID, float], dict[uuid.UUID, list]]:
    """Weighted RRF over chunk rankings, then collapse to articles (max chunk score).

    score(chunk) = sum_i  w_i / (k + rank_i)
    """
    weights = weights or [1.0] * len(ranked_lists)
    chunk_score: dict[uuid.UUID, float] = {}
    chunk_info: dict[uuid.UUID, Candidate] = {}
    for lst, w in zip(ranked_lists, weights, strict=True):
        for rank, cand in enumerate(lst, start=1):
            chunk_score[cand.chunk_id] = chunk_score.get(cand.chunk_id, 0.0) + w / (k + rank)
            chunk_info[cand.chunk_id] = cand
    article_score: dict[uuid.UUID, float] = {}
    article_chunks: dict[uuid.UUID, list] = {}
    for cid, sc in sorted(chunk_score.items(), key=lambda kv: -kv[1]):
        aid = chunk_info[cid].article_id
        article_score[aid] = max(article_score.get(aid, 0.0), sc)
        article_chunks.setdefault(aid, []).append(chunk_info[cid])
    return article_score, article_chunks


def retrieve(
    s: Session,
    question: str,
    settings: Settings,
    embedder: EmbeddingProvider,
    document_ids: list[uuid.UUID] | None = None,
) -> RetrievalResult:
    doc_ids = [str(d) for d in document_ids] if document_ids else None
    limit = settings.retrieval_candidate_limit
    lists: list[list[Candidate]] = []
    weights: list[float] = []
    tokens = 0

    def add(lst: list[Candidate], w: float) -> None:
        if w > 0 and lst:
            lists.append(lst)
            weights.append(w)

    for variant in query_variants(question):
        tokens += estimate_tokens(variant)
        add(
            semantic_search(s, embedder.embed_query(variant), embedder.space, doc_ids, limit),
            settings.retrieval_semantic_weight,
        )
        add(lexical_search(s, variant, doc_ids, limit), settings.retrieval_lexical_weight)
        add(article_ref_search(s, variant, doc_ids, limit), settings.retrieval_article_ref_weight)
        if settings.retrieval_title_list:
            add(title_search(s, variant, doc_ids, limit), settings.retrieval_lexical_weight)
    article_score, article_chunks = rrf_fuse(lists, settings.retrieval_rrf_k, weights)
    ranked = sorted(article_score, key=lambda a: -article_score[a])
    top = ranked[: settings.retrieval_top_k]
    articles = _load_articles(s, top, article_score, article_chunks)
    articles = assemble_context(s, articles, settings.context_max_tokens)
    return RetrievalResult(articles, ranked, embedder.space, tokens)


def _load_articles(s: Session, ids, scores, chunks) -> list[RetrievedArticle]:
    if not ids:
        return []
    rows = s.execute(
        text("""SELECT a.id, d.id, d.title, a.version_id, a.label, a.title, a.heading_context, a.text,
                       a.source_url, d.last_checked_at, a.future_effective
                FROM articles a JOIN document_versions v ON v.id = a.version_id
                JOIN documents d ON d.id = v.document_id
                WHERE a.id IN :ids""").bindparams(bindparam("ids", expanding=True)),
        {"ids": list(ids)},
    ).all()
    by_id = {r[0]: r for r in rows}
    out = []
    for aid in ids:
        r = by_id[aid]
        out.append(
            RetrievedArticle(
                article_id=r[0],
                document_id=r[1],
                document_title=r[2],
                version_id=r[3],
                label=r[4],
                title=r[5],
                heading_context=r[6],
                full_text=r[7],
                context_text="",
                source_url=r[8],
                checked_at=r[9],
                future_effective=r[10],
                score=scores[aid],
                matched_chunk_ids=[c.chunk_id for c in chunks[aid]],
            )
        )
    return out


def assemble_context(s: Session, articles: list[RetrievedArticle], max_tokens: int) -> list[RetrievedArticle]:
    """Bounded context; one source per article (chunks are never duplicated)."""
    kept, used = [], 0
    for art in articles:
        if estimate_tokens(art.full_text) <= PER_ARTICLE_TOKEN_CAP:
            body = art.full_text
        else:
            rows = s.execute(
                text("SELECT id, ordinal, text FROM chunks WHERE article_id = :a ORDER BY ordinal"),
                {"a": art.article_id},
            ).all()
            matched = {r[1] for r in rows if r[0] in set(art.matched_chunk_ids)}
            wanted = sorted({o + d for o in matched for d in (-1, 0, 1)})
            parts, budget = [], PER_ARTICLE_TOKEN_CAP
            for r in rows:
                if r[1] in wanted and estimate_tokens(r[2]) <= budget:
                    parts.append(r[2])
                    budget -= estimate_tokens(r[2])
            body = "\n[…]\n".join(parts) if parts else rows[0][2]
        cost = estimate_tokens(body) + 40
        if used + cost > max_tokens:
            if kept:
                break
            body = body[: max_tokens * 4]
            cost = max_tokens
        art.context_text = body
        used += cost
        kept.append(art)
    for i, art in enumerate(kept, start=1):
        art.source_id = f"S{i}"
    return kept
