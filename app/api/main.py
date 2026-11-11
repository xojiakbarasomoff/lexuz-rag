"""FastAPI application. Handlers stay thin; logic lives in generation/ retrieval/ ingestion/."""

from __future__ import annotations

import hmac
import time
import uuid
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.errors import error_payload
from app.core.config import get_settings
from app.core.limits import GuardUnavailable, RateLimited, get_guards
from app.core.logging import configure_logging, get_logger, request_id_var
from app.db.session import get_db
from app.generation.answer import AnswerError, answer_question
from app.models import Article, Document, DocumentVersion
from app.observability import metrics
from app.schemas import (
    ArticleSummary,
    AskRequest,
    AskResponse,
    DocumentDetail,
    DocumentSummary,
    ErrorResponse,
)

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger("api")

app = FastAPI(
    title="LexUZ RAG API",
    version="0.1.0",
    description="Source-grounded answers about indexed Uzbek legislation. Not an official Lex.uz product.",
    docs_url="/api/docs" if settings.enable_api_docs else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if settings.enable_api_docs else None,
)
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
    )

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = uuid.uuid4().hex
    request.state.request_id = rid
    token = request_id_var.set(rid)
    t0 = time.perf_counter()
    route = "other"
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    r = request.scope.get("route")
    route = getattr(r, "path", None) or ("static" if request.url.path.startswith("/") else "other")
    elapsed = time.perf_counter() - t0
    metrics.http_requests.labels(route=route, method=request.method, status=str(response.status_code)).inc()
    metrics.http_latency.labels(route=route).observe(elapsed)
    response.headers["X-Request-ID"] = rid
    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    if route.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def _err(request: Request, code: str, headers: dict | None = None) -> JSONResponse:
    status, body = error_payload(code, getattr(request.state, "request_id", "-"))
    return JSONResponse(body, status_code=status, headers=headers)


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, _exc):
    return _err(request, "invalid_request")


@app.exception_handler(StarletteHTTPException)
async def _http_handler(request: Request, exc: StarletteHTTPException):
    return _err(request, "not_found" if exc.status_code == 404 else "invalid_request")


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    log.exception("unhandled_error", error_type=type(exc).__name__)
    return _err(request, "internal_error")


# ----------------------------------------------------------------------------- ask

ERROR_RESPONSES = {429: {"model": ErrorResponse}, 503: {"model": ErrorResponse}, 422: {"model": ErrorResponse}}


@app.post("/api/v1/ask", response_model=AskResponse, responses=ERROR_RESPONSES, tags=["ask"])
def ask(req: AskRequest, request: Request):
    rid = request.state.request_id
    ip = request.client.host if request.client else "unknown"
    try:
        get_guards().check_rate(ip)
    except GuardUnavailable:
        metrics.rate_limited.labels(reason="guard_unavailable").inc()
        return _err(request, "generation_unavailable")
    except RateLimited as exc:
        metrics.rate_limited.labels(reason=exc.scope).inc()
        return _err(
            request,
            "rate_limited" if exc.scope == "minute" else "daily_limit",
            headers={"Retry-After": str(exc.retry_after)},
        )
    try:
        resp = answer_question(req.question, document_ids=req.document_ids, request_id=rid)
    except GuardUnavailable:
        return _err(request, "generation_unavailable")
    except AnswerError as exc:
        log.warning("ask_failed", code=exc.code, question_chars=len(req.question))
        return _err(request, exc.code)
    log.info(
        "ask_done",
        status=resp.status,
        claims=len(resp.claims),
        sources=len(resp.sources),
        latency_ms=resp.latency_ms,
        question_chars=len(req.question),
        **({"question": req.question} if settings.log_question_text else {}),
    )
    return resp


# ----------------------------------------------------------------------------- documents


def _summary(s: Session, d: Document) -> dict:
    v = s.get(DocumentVersion, d.active_version_id) if d.active_version_id else None
    return dict(
        id=d.id,
        title=d.title,
        canonical_url=d.canonical_url,
        language=d.language,
        official_status=d.official_status,
        doc_number=d.doc_number,
        adoption_date=d.adoption_date,
        entry_into_force_date=d.entry_into_force_date,
        last_checked_at=d.last_checked_at,
        active_version_id=d.active_version_id,
        source_revision_label=v.source_revision_label if v else None,
        article_count=v.article_count if v else 0,
    ), v


@app.get("/api/v1/documents", response_model=list[DocumentSummary], tags=["documents"])
def list_documents(db: Session = Depends(get_db)):
    docs = db.scalars(select(Document).where(Document.active_version_id.is_not(None)).order_by(Document.title)).all()
    return [DocumentSummary(**_summary(db, d)[0]) for d in docs]


@app.get(
    "/api/v1/documents/{document_id}",
    response_model=DocumentDetail,
    responses={404: {"model": ErrorResponse}},
    tags=["documents"],
)
def get_document(document_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    d = db.get(Document, document_id)
    if d is None or d.active_version_id is None:
        return _err(request, "not_found")
    data, v = _summary(db, d)
    arts = db.scalars(select(Article).where(Article.version_id == d.active_version_id).order_by(Article.ordinal)).all()
    return DocumentDetail(
        **data,
        source_kind=v.source_kind if v else None,
        articles=[
            ArticleSummary(
                id=a.id,
                label=a.label,
                title=a.title,
                heading_context=a.heading_context,
                source_url=a.source_url,
                status=a.status,
            )
            for a in arts
        ],
    )


# ----------------------------------------------------------------------------- health / metrics


@app.get("/health/live", tags=["health"])
def live():
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def ready(db: Session = Depends(get_db)):
    checks: dict[str, str] = {}
    try:
        db.execute(text("SELECT 1"))
        active = db.scalar(select(func.count()).select_from(Document).where(Document.active_version_id.is_not(None)))
        oldest = db.scalar(select(func.min(Document.last_checked_at)).where(Document.active_version_id.is_not(None)))
        checks["database"] = "ok"
        checks["corpus"] = "ok" if active else "empty"
        if oldest:
            metrics.corpus_age_seconds.set((datetime.now(UTC) - oldest).total_seconds())
    except Exception:
        checks["database"] = "error"
    checks["redis"] = "ok" if get_guards().ping() else "error"
    checks["generation"] = "enabled" if checks["redis"] == "ok" else "disabled"
    ok = checks["database"] == "ok" and checks.get("corpus") == "ok"
    return JSONResponse({"status": "ok" if ok else "unavailable", "checks": checks}, status_code=200 if ok else 503)


@app.get("/internal/metrics", include_in_schema=False)
def internal_metrics(request: Request):
    token = settings.metrics_token
    if token:
        given = request.headers.get("authorization", "").removeprefix("Bearer ")
        if not hmac.compare_digest(given, token):
            return PlainTextResponse("forbidden", status_code=403)
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


if settings.serve_frontend and settings.frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
