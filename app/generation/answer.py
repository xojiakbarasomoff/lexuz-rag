"""Question → retrieval → guarded LLM call → validation → trusted citations."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select

from app.core.config import Settings, get_settings
from app.core.limits import BudgetExceeded, Busy, Guards, LLMQuotaExceeded, estimate_cost_usd, get_guards
from app.core.logging import get_logger
from app.db.session import get_sessionmaker
from app.generation.prompt import (
    OUTPUT_SCHEMA,
    SYSTEM_PROMPT,
    build_repair_message,
    build_user_message,
)
from app.generation.validate import ValidationOutcome, validate_output
from app.ingestion.chunker import estimate_tokens
from app.models import Document, UsageEvent
from app.observability import metrics
from app.providers.embeddings import EmbeddingProvider, get_embedding_provider
from app.providers.llm import LLMError, LLMProvider, get_llm_provider
from app.retrieval.search import RetrievedArticle, retrieve
from app.schemas import AskResponse, Claim, Source

log = get_logger(__name__)

MSG_NO_EVIDENCE = (
    "Indekslangan hujjatlarda bu savolga javob beradigan aniq qoida topilmadi. "
    "Hozircha faqat quyidagi hujjatlar qamrab olingan: {titles}."
)
MSG_FALLBACK = (
    "Javobni manbalar bilan ishonchli tekshirib bo‘lmadi, shuning uchun u ko‘rsatilmadi. "
    "Quyidagi moddalarni rasmiy matnda o‘qib chiqing yoki savolni aniqroq yozing."
)


class AnswerError(Exception):
    """Errors with a stable public code (mapped to HTTP status in the API)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass
class Deps:
    settings: Settings
    llm: LLMProvider
    embedder: EmbeddingProvider
    guards: Guards | None  # None = no guards (CLI only)
    session_factory: object = None
    budget_scope: str = "public"  # separate Redis budget, e.g. "eval-<run>"


@dataclass
class AnswerTrace:
    """Internal; used by evals. Never returned by the public API."""

    retrieved_article_ids: list[uuid.UUID] = field(default_factory=list)
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    est_cost_usd: float = 0.0
    repaired: bool = False
    fallback: bool = False
    provider_blocked: str | None = None  # provider safety block reason (not missing evidence)
    model_versions: set = field(default_factory=set)  # model versions reported by the provider
    validation_errors: list[str] = field(default_factory=list)


_default_deps: Deps | None = None


def default_deps() -> Deps:
    global _default_deps
    if _default_deps is None:
        s = get_settings()
        _default_deps = Deps(s, get_llm_provider(s), get_embedding_provider(s), get_guards())
    return _default_deps


def _corpus(session, document_ids):
    q = select(Document).where(Document.active_version_id.is_not(None))
    if document_ids:
        q = q.where(Document.id.in_(document_ids))
    docs = session.scalars(q).all()
    checked = session.scalar(select(func.min(Document.last_checked_at)).where(Document.id.in_([d.id for d in docs])))
    return docs, checked


def _record_usage(session_factory, *, kind, model, in_tok, out_tok, cost, request_id, outcome) -> None:
    try:
        with session_factory() as s:
            s.add(
                UsageEvent(
                    kind=kind,
                    model=model,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    est_cost_usd=cost,
                    request_id=request_id,
                    outcome=outcome,
                )
            )
            s.commit()
    except Exception:  # monitoring must never break answering
        log.warning("usage_record_failed")


def _guarded_call(deps: Deps, trace: AnswerTrace, user: str, request_id: str) -> str:
    s = deps.settings
    call_id = f"{request_id}:{trace.llm_calls}"
    est_in = int(estimate_tokens(SYSTEM_PROMPT + user) * 1.3) + 200
    # Worst case: full output budget on every SDK attempt (initial + retries).
    est_cost = estimate_cost_usd(s, est_in, s.llm_max_output_tokens) * (1 + s.llm_max_retries)
    g = deps.guards
    if g:
        g.acquire_slot(call_id)
    try:
        if g:
            g.check_llm_quota()  # project-wide free-tier caps; counts repairs too
            g.reserve(call_id, est_cost, scope=deps.budget_scope)
        trace.llm_calls += 1
        t0 = time.perf_counter()
        try:
            res = deps.llm.complete_json(
                system=SYSTEM_PROMPT, user=user, schema=OUTPUT_SCHEMA, max_tokens=s.llm_max_output_tokens
            )
        except LLMError as exc:
            billed_in, billed_out = getattr(exc, "input_tokens", 0), getattr(exc, "output_tokens", 0)
            if billed_in or billed_out:
                actual = estimate_cost_usd(s, billed_in, billed_out)
            else:
                actual = 0.0 if exc.code in LLMError.NOT_BILLED else est_cost  # timeout: may be billed
            if g:
                g.settle(call_id, actual, scope=deps.budget_scope)
                if exc.code == "provider_quota":
                    g.mark_provider_quota_exhausted()
            trace.est_cost_usd += actual
            metrics.provider_errors.labels(code=exc.code).inc()
            _record_usage(
                deps.session_factory,
                kind="ask_llm",
                model=deps.llm.model,
                in_tok=billed_in,
                out_tok=billed_out,
                cost=actual,
                request_id=request_id,
                outcome=exc.code,
            )
            raise
        actual = estimate_cost_usd(s, res.input_tokens, res.output_tokens)
        trace.model_versions.add(res.model)
        if g:
            g.settle(call_id, actual, scope=deps.budget_scope)
        trace.input_tokens += res.input_tokens
        trace.output_tokens += res.output_tokens
        trace.est_cost_usd += actual
        metrics.llm_tokens.labels(direction="input").inc(res.input_tokens)
        metrics.llm_tokens.labels(direction="output").inc(res.output_tokens)
        metrics.llm_cost.inc(actual)
        metrics.llm_latency.observe(time.perf_counter() - t0)
        _record_usage(
            deps.session_factory,
            kind="ask_llm",
            model=res.model,
            in_tok=res.input_tokens,
            out_tok=res.output_tokens,
            cost=actual,
            request_id=request_id,
            outcome="ok",
        )
        return res.text
    finally:
        if g:
            g.release_slot(call_id)


def _sources_for(claims, by_sid: dict[str, RetrievedArticle], outcome: ValidationOutcome) -> list[Source]:
    order: list[str] = []
    for c in claims:
        for sid in c.source_ids:
            if sid not in order:
                order.append(sid)
    excerpts: dict[str, str] = {}
    for vc in outcome.claims:
        for sid, ex in vc.excerpts.items():
            excerpts.setdefault(sid, ex[0])
    out = []
    for sid in order:
        a = by_sid[sid]
        out.append(
            Source(
                source_id=sid,
                document_id=a.document_id,
                document_title=a.document_title,
                article_label=a.label,
                article_title=a.title,
                excerpt=excerpts.get(sid) or a.full_text[:300],
                source_url=a.source_url,
                version_id=a.version_id,
                checked_at=a.checked_at,
                has_future_amendment_note=a.future_effective,
            )
        )
    return out


def _related_sources(articles: list[RetrievedArticle], n: int = 3) -> list[Source]:
    return [
        Source(
            source_id=a.source_id,
            document_id=a.document_id,
            document_title=a.document_title,
            article_label=a.label,
            article_title=a.title,
            excerpt=a.full_text[:300],
            source_url=a.source_url,
            version_id=a.version_id,
            checked_at=a.checked_at,
            has_future_amendment_note=a.future_effective,
        )
        for a in articles[:n]
    ]


def answer_question(
    question: str,
    *,
    document_ids: list[uuid.UUID] | None,
    request_id: str | None = None,
    deps: Deps | None = None,
    trace: AnswerTrace | None = None,
) -> AskResponse:
    t0 = time.perf_counter()
    deps = deps or default_deps()
    if deps.session_factory is None:
        deps.session_factory = get_sessionmaker()
    request_id = request_id or uuid.uuid4().hex
    trace = trace if trace is not None else AnswerTrace()
    settings = deps.settings

    def done(**kw) -> AskResponse:
        resp = AskResponse(request_id=request_id, latency_ms=int((time.perf_counter() - t0) * 1000), **kw)
        metrics.answers.labels(status=resp.status).inc()
        return resp

    with deps.session_factory() as session:
        docs, checked_at = _corpus(session, document_ids)
        if not docs:
            raise AnswerError("corpus_unavailable", "no active documents")
        titles = [d.title for d in docs]
        result = retrieve(session, question, settings, deps.embedder, [d.id for d in docs])
    trace.retrieved_article_ids = result.ranked_article_ids
    _record_usage(
        deps.session_factory,
        kind="query_embedding",
        model=deps.embedder.space,
        in_tok=result.query_tokens_est,
        out_tok=0,
        cost=result.query_tokens_est * deps.embedder.price_per_mtok_usd / 1e6,
        request_id=request_id,
        outcome="ok",
    )

    if not result.articles:
        return done(
            status="insufficient_evidence",
            limitations=[MSG_NO_EVIDENCE.format(titles="; ".join(titles))],
            corpus_checked_at=checked_at,
        )

    by_sid = {a.source_id: a for a in result.articles}
    source_texts = {a.source_id: a.full_text for a in result.articles}
    user = build_user_message(question, result.articles, titles)

    try:
        raw = _guarded_call(deps, trace, user, request_id)
        outcome = validate_output(raw, source_texts)
        if not outcome.ok:
            trace.validation_errors = outcome.errors
            trace.repaired = True
            metrics.validation_failures.labels(stage="first").inc()
            raw = _guarded_call(deps, trace, build_repair_message(user, raw, outcome.errors), request_id)
            outcome = validate_output(raw, source_texts)
            if not outcome.ok:
                metrics.validation_failures.labels(stage="repair").inc()
                trace.validation_errors += outcome.errors
    except BudgetExceeded as exc:
        raise AnswerError("budget_exhausted") from exc
    except Busy as exc:
        raise AnswerError("busy") from exc
    except LLMQuotaExceeded as exc:
        raise AnswerError("quota_exhausted", exc.scope) from exc
    except LLMError as exc:
        if exc.code == "provider_blocked":
            trace.provider_blocked = exc.detail or "blocked"
            log.warning("answer_provider_blocked", reason=exc.detail)
            return done(
                status="provider_blocked",
                corpus_checked_at=checked_at,
                limitations=[
                    "AI xizmatining xavfsizlik filtri bu savolga javobni to‘xtatdi. Bu manba yo‘qligini "
                    "anglatmaydi; savolni boshqacha, umumiy shaklda yozib ko‘ring."
                ],
            )
        raise AnswerError(exc.code, exc.detail) from exc

    if not outcome.ok:
        trace.fallback = True
        log.warning("answer_fallback", errors=len(trace.validation_errors))
        return done(
            status="insufficient_evidence",
            limitations=[MSG_FALLBACK],
            sources=_related_sources(result.articles),
            corpus_checked_at=checked_at,
        )

    limitations = list(outcome.limitations)
    if outcome.status == "insufficient_evidence" and not limitations:
        limitations = [MSG_NO_EVIDENCE.format(titles="; ".join(titles))]
    claims = [Claim(text=c.text, source_ids=c.source_ids) for c in outcome.claims]
    if outcome.status != "answered":
        # Partial claims of a non-answer are dropped: they would read as an answer.
        claims = []
    return done(
        status=outcome.status,
        claims=claims,
        sources=_sources_for(claims, by_sid, outcome),
        clarifying_question=outcome.clarifying_question if outcome.status == "clarification_needed" else None,
        limitations=limitations,
        corpus_checked_at=checked_at,
    )
