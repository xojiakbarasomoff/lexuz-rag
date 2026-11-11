"""Ingestion pipeline: fetch → snapshot → parse → validate → chunk → embed → activate.

Guarantees:
- Idempotent: identical parsed content maps to the existing version
  (unique (document_id, content_checksum)); embeddings are keyed by
  (content_hash, embedding_space) and never recomputed for unchanged text.
- One running job per document (partial unique index).
- No DB transaction is held open during network calls or embedding.
- A new version becomes visible to retrieval only through `activate_version`,
  a single transaction that flips `documents.active_version_id`.
- Any failure (fetch, parse, validation, embedding) leaves the previously
  active version untouched.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.session import session_scope
from app.ingestion.chunker import chunk_article
from app.ingestion.fetcher import FetchError, fetch_source, store_snapshot
from app.ingestion.parser_lexuz import PARSER_VERSION, ParsedDocument, parse_lexuz_html
from app.ingestion.sources import SourceSpec, get_source
from app.ingestion.validate import validate_parsed
from app.models import (
    Article,
    Chunk,
    ChunkEmbedding,
    Document,
    DocumentVersion,
    IngestionJob,
    JobStatus,
    VersionStatus,
)
from app.providers.embeddings import EmbeddingProvider, get_embedding_provider

log = get_logger(__name__)
TASHKENT = ZoneInfo("Asia/Tashkent")
STALE_JOB_AFTER = timedelta(hours=2)


class JobAlreadyRunning(Exception):
    pass


@dataclass
class IngestResult:
    job_id: uuid.UUID
    status: str
    version_id: uuid.UUID | None = None
    error_code: str | None = None
    detail: str | None = None


@dataclass
class RawSource:
    body: bytes
    fetched_at: datetime
    source_kind: str  # live_fetch | local_import
    provenance: dict


def today_tashkent(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(TASHKENT).date()


def content_checksum(parsed: ParsedDocument) -> str:
    canonical = [
        {"l": a.label, "t": a.title, "h": a.heading_context, "x": a.text, "n": a.notes} for a in parsed.articles
    ]
    payload = json.dumps({"p": PARSER_VERSION, "title": parsed.title, "a": canonical}, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def article_url(spec: SourceSpec, anchor: str | None) -> str:
    return f"{spec.url}#{anchor}" if anchor else spec.url


# --------------------------------------------------------------------------- jobs


def ensure_document(spec: SourceSpec) -> uuid.UUID:
    with session_scope() as s:
        doc = s.scalar(select(Document).where(Document.source_key == spec.key))
        if doc is None:
            doc = Document(
                source_key=spec.key,
                title=spec.short_name,
                official_id=spec.lexuz_id,
                canonical_url=spec.url,
                language=spec.language,
            )
            s.add(doc)
            s.flush()
        return doc.id


def _start_job(document_id: uuid.UUID, trigger: str) -> uuid.UUID:
    with session_scope() as s:
        s.execute(
            update(IngestionJob)
            .where(
                IngestionJob.document_id == document_id,
                IngestionJob.status == JobStatus.RUNNING,
                IngestionJob.started_at < datetime.now(UTC) - STALE_JOB_AFTER,
            )
            .values(status=JobStatus.FAILED, error_code="stale", finished_at=datetime.now(UTC))
        )
    try:
        with session_scope() as s:
            job = IngestionJob(document_id=document_id, status=JobStatus.RUNNING, trigger=trigger)
            s.add(job)
            s.flush()
            return job.id
    except IntegrityError as exc:
        raise JobAlreadyRunning(str(document_id)) from exc


def _finish_job(job_id: uuid.UUID, status: str, **fields) -> None:
    with session_scope() as s:
        s.execute(
            update(IngestionJob)
            .where(IngestionJob.id == job_id)
            .values(status=status, finished_at=datetime.now(UTC), **fields)
        )


# --------------------------------------------------------------------------- main entry


def ingest_source(
    source_key: str,
    *,
    trigger: str = "cli",
    raw: RawSource | None = None,
    settings: Settings | None = None,
    embedder: EmbeddingProvider | None = None,
    now: datetime | None = None,
) -> IngestResult:
    """Run one ingestion. `raw` is given for local-file imports and tests;
    otherwise the pre-approved URL is fetched."""
    settings = settings or get_settings()
    spec = get_source(source_key)
    document_id = ensure_document(spec)
    job_id = _start_job(document_id, trigger)
    log.info("ingest_start", source=source_key, job_id=str(job_id))
    try:
        return _run(job_id, document_id, spec, raw, settings, embedder, now)
    except Exception as exc:  # never leave a job 'running'
        log.exception("ingest_crashed", job_id=str(job_id))
        _finish_job(job_id, JobStatus.FAILED, error_code="internal_error", error_detail=str(exc)[:2000])
        _record_check_error(document_id, f"internal_error: {exc}")
        raise


def _record_check_error(document_id: uuid.UUID, message: str) -> None:
    with session_scope() as s:
        s.execute(update(Document).where(Document.id == document_id).values(last_check_error=message[:2000]))


def _run(job_id, document_id, spec, raw, settings, embedder, now) -> IngestResult:
    # 1. fetch (no transaction open)
    if raw is None:
        with session_scope() as s:
            prev = s.scalar(
                select(DocumentVersion)
                .where(DocumentVersion.document_id == document_id, DocumentVersion.source_kind == "live_fetch")
                .order_by(DocumentVersion.fetched_at.desc())
                .limit(1)
            )
            prev_headers = (prev.provenance or {}).get("response_headers", {}) if prev else {}
        try:
            res = fetch_source(
                spec.url, settings, etag=prev_headers.get("etag"), last_modified=prev_headers.get("last-modified")
            )
        except FetchError as exc:
            _finish_job(job_id, JobStatus.FAILED, error_code=f"fetch_{exc.code}", error_detail=exc.detail[:2000])
            _record_check_error(document_id, f"fetch_{exc.code}: {exc.detail}")
            return IngestResult(job_id, JobStatus.FAILED, error_code=f"fetch_{exc.code}", detail=exc.detail)
        if res.not_modified:
            with session_scope() as s:
                s.execute(
                    update(Document)
                    .where(Document.id == document_id)
                    .values(last_checked_at=res.fetched_at, last_check_error=None)
                )
            _finish_job(job_id, JobStatus.UNCHANGED)
            return IngestResult(job_id, JobStatus.UNCHANGED)
        keep = {k: v for k, v in res.headers.items() if k.lower() in ("etag", "last-modified", "content-type", "date")}
        raw = RawSource(
            body=res.body or b"",
            fetched_at=res.fetched_at,
            source_kind="live_fetch",
            provenance={
                "url": spec.url,
                "final_url": res.final_url,
                "http_status": res.status_code,
                "response_headers": {k.lower(): v for k, v in keep.items()},
            },
        )

    # 2. snapshot
    snap_path, raw_sha = store_snapshot(settings.snapshot_dir, spec.key, raw.body, raw.fetched_at)
    as_of = today_tashkent(now)

    # 3. parse + validate
    try:
        html = raw.body.decode("utf-8")
    except UnicodeDecodeError:
        html = raw.body.decode("utf-8", errors="replace")
    parsed = parse_lexuz_html(html, as_of=as_of)
    checksum = content_checksum(parsed)

    with session_scope() as s:
        doc = s.get(Document, document_id)
        existing = s.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == document_id, DocumentVersion.content_checksum == checksum
            )
        )
        if existing is not None and existing.id == doc.active_version_id:
            doc.last_checked_at = raw.fetched_at
            doc.last_check_error = None
            existing_id = existing.id
            already_active = True
        else:
            already_active = False
            existing_id = existing.id if existing else None
            existing_status = existing.status if existing else None
        prev_labels = None
        if doc.active_version_id:
            prev_labels = set(s.scalars(select(Article.label).where(Article.version_id == doc.active_version_id)))

    if already_active:
        _finish_job(job_id, JobStatus.UNCHANGED, fetched_bytes=len(raw.body), version_id=existing_id)
        log.info("ingest_unchanged", source=spec.key)
        return IngestResult(job_id, JobStatus.UNCHANGED, existing_id)

    report = validate_parsed(parsed, spec, previous_labels=prev_labels, as_of=as_of)
    outcome = report.outcome

    if existing_id is not None:
        version_id = existing_id
        if existing_status in (VersionStatus.REJECTED,):
            _finish_job(
                job_id,
                JobStatus.FAILED,
                error_code="validation_failed",
                version_id=version_id,
                error_detail="; ".join(report.errors)[:2000],
            )
            return IngestResult(job_id, JobStatus.FAILED, version_id, "validation_failed")
    else:
        version_id = _store_version(document_id, spec, parsed, report, raw, snap_path, raw_sha, checksum, settings)

    if outcome == "rejected":
        _finish_job(
            job_id,
            JobStatus.FAILED,
            error_code="validation_failed",
            version_id=version_id,
            fetched_bytes=len(raw.body),
            articles_parsed=len(parsed.articles),
            error_detail="; ".join(report.errors)[:2000],
        )
        _record_check_error(document_id, "validation_failed: " + "; ".join(report.errors))
        log.warning("ingest_rejected", source=spec.key, errors=report.errors)
        return IngestResult(job_id, JobStatus.FAILED, version_id, "validation_failed", "; ".join(report.errors))

    # 4. embeddings (outside any long transaction)
    embedder = embedder or get_embedding_provider(settings)
    created = embed_missing_for_version(version_id, embedder)
    with session_scope() as s:
        n_chunks = s.query(Chunk).filter(Chunk.version_id == version_id).count()
        v = s.get(DocumentVersion, version_id)
        if v.status == VersionStatus.PARSED:
            v.status = VersionStatus.INDEXED if outcome == "ok" else VersionStatus.NEEDS_REVIEW

    stats = dict(
        fetched_bytes=len(raw.body),
        articles_parsed=len(parsed.articles),
        chunks_indexed=n_chunks,
        embeddings_created=created,
        version_id=version_id,
    )
    if outcome == "needs_review":
        _finish_job(
            job_id,
            JobStatus.NEEDS_REVIEW,
            error_code="manual_review_required",
            error_detail="; ".join(report.review_reasons)[:2000],
            **stats,
        )
        _record_check_error(document_id, "manual_review_required: " + "; ".join(report.review_reasons))
        log.warning("ingest_needs_review", source=spec.key, reasons=report.review_reasons)
        return IngestResult(job_id, JobStatus.NEEDS_REVIEW, version_id, "manual_review_required")

    activate_version(version_id, embedding_space=embedder.space, checked_at=raw.fetched_at)
    _finish_job(job_id, JobStatus.SUCCEEDED, activated_version_id=version_id, **stats)
    log.info(
        "ingest_activated",
        source=spec.key,
        version_id=str(version_id),
        **{k: v for k, v in stats.items() if k != "version_id"},
    )
    return IngestResult(job_id, JobStatus.SUCCEEDED, version_id)


def _store_version(document_id, spec, parsed, report, raw, snap_path, raw_sha, checksum, settings) -> uuid.UUID:
    status = VersionStatus.REJECTED if report.outcome == "rejected" else VersionStatus.PARSED
    with session_scope() as s:
        v = DocumentVersion(
            document_id=document_id,
            content_checksum=checksum,
            raw_checksum=raw_sha,
            fetched_at=raw.fetched_at,
            source_kind=raw.source_kind,
            source_revision_label=parsed.revision_label,
            raw_snapshot_path=snap_path,
            provenance={
                **raw.provenance,
                "parsed_title": parsed.title,
                "header_label": parsed.header_label,
                "adoption_date": parsed.adoption_date.isoformat() if parsed.adoption_date else None,
                "doc_number": parsed.doc_number,
                "entry_into_force_date": (
                    parsed.entry_into_force_date.isoformat() if parsed.entry_into_force_date else None
                ),
            },
            status=status,
            parser_version=PARSER_VERSION,
            validation=report.to_dict(),
            article_count=len(parsed.articles),
        )
        s.add(v)
        s.flush()
        if status == VersionStatus.REJECTED:
            return v.id
        for i, a in enumerate(parsed.articles):
            art = Article(
                version_id=v.id,
                label=a.label,
                ordinal=i,
                title=a.title,
                heading_context=a.heading_context,
                text=a.text,
                notes=a.notes,
                source_anchor=a.anchor,
                source_url=article_url(spec, a.anchor),
                status="repealed" if a.is_repealed else "in_force",
                future_effective=bool(a.future_effective_dates),
                content_hash=hashlib.sha256(f"{a.label}\n{a.title}\n{a.text}".encode()).hexdigest(),
            )
            s.add(art)
            s.flush()
            if a.is_repealed:
                continue  # repealed articles are kept for audit but never indexed
            for c in chunk_article(
                doc_short_name=spec.short_name,
                label=a.label,
                title=a.title,
                heading_context=a.heading_context,
                paragraphs=a.paragraphs,
                max_chars=settings.chunk_max_chars,
                overlap_paragraphs=settings.chunk_overlap_paragraphs,
                overlap_max_chars=settings.chunk_overlap_max_chars,
            ):
                s.add(
                    Chunk(
                        article_id=art.id,
                        version_id=v.id,
                        ordinal=c.ordinal,
                        text=c.text,
                        embed_text=c.embed_text,
                        search_text=c.search_text,
                        content_hash=c.content_hash,
                        char_len=c.char_len,
                        est_tokens=c.est_tokens,
                    )
                )
        return v.id


def embed_missing_for_version(version_id: uuid.UUID, embedder: EmbeddingProvider, batch_size: int = 32) -> int:
    """Embed chunks whose (content_hash, space) has no vector yet. Safe to re-run."""
    with session_scope() as s:
        have = select(ChunkEmbedding.content_hash).where(ChunkEmbedding.embedding_space == embedder.space)
        rows = s.execute(
            select(Chunk.content_hash, Chunk.embed_text)
            .where(Chunk.version_id == version_id, Chunk.content_hash.not_in(have))
            .distinct()
        ).all()
    created = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        vectors = embedder.embed_documents([r.embed_text for r in batch])
        with session_scope() as s:
            stmt = (
                pg_insert(ChunkEmbedding)
                .values(
                    [
                        {"content_hash": r.content_hash, "embedding_space": embedder.space, "embedding": vec}
                        for r, vec in zip(batch, vectors, strict=True)
                    ]
                )
                .on_conflict_do_nothing()
                .returning(ChunkEmbedding.content_hash)
            )
            created += len(s.execute(stmt).all())
        log.info("embedded_batch", done=min(i + batch_size, len(rows)), total=len(rows))
    return created


def missing_embeddings(version_id: uuid.UUID, space: str) -> int:
    with session_scope() as s:
        have = select(ChunkEmbedding.content_hash).where(ChunkEmbedding.embedding_space == space)
        return s.query(Chunk).filter(Chunk.version_id == version_id, Chunk.content_hash.not_in(have)).count()


def activate_version(
    version_id: uuid.UUID, *, embedding_space: str, checked_at: datetime | None = None, force_review: bool = False
) -> None:
    """Atomically make `version_id` the active version of its document."""
    if missing_embeddings(version_id, embedding_space):
        raise ValueError("version is not fully embedded for the current embedding space")
    with session_scope() as s:
        v = s.get(DocumentVersion, version_id)
        if v.status == VersionStatus.NEEDS_REVIEW and not force_review:
            raise ValueError("version needs manual review; use approve-version")
        if v.status not in (VersionStatus.INDEXED, VersionStatus.NEEDS_REVIEW, VersionStatus.SUPERSEDED):
            raise ValueError(f"cannot activate a version in status {v.status}")
        doc = s.execute(select(Document).where(Document.id == v.document_id).with_for_update()).scalar_one()
        if doc.active_version_id and doc.active_version_id != v.id:
            s.execute(
                update(DocumentVersion)
                .where(DocumentVersion.id == doc.active_version_id)
                .values(status=VersionStatus.SUPERSEDED)
            )
        v.status = VersionStatus.ACTIVE
        v.activated_at = datetime.now(UTC)
        p = v.provenance or {}
        doc.active_version_id = v.id
        doc.title = p.get("parsed_title") or doc.title
        doc.doc_number = p.get("doc_number")
        doc.adoption_date = date.fromisoformat(p["adoption_date"]) if p.get("adoption_date") else None
        doc.entry_into_force_date = (
            date.fromisoformat(p["entry_into_force_date"]) if p.get("entry_into_force_date") else None
        )
        doc.last_checked_at = checked_at or v.fetched_at
        doc.last_check_error = None


def approve_version(version_id: uuid.UUID, embedding_space: str) -> None:
    """Manual approval of a `needs_review` version after a human checked it."""
    activate_version(version_id, embedding_space=embedding_space, force_review=True)


def load_local_file(path: Path, *, source_url: str, retrieved_at: datetime, note: str = "") -> RawSource:
    """Import a file that a person downloaded from the official source.

    This is NOT live synchronization: provenance records it as a local import.
    """
    return RawSource(
        body=path.read_bytes(),
        fetched_at=retrieved_at,
        source_kind="local_import",
        provenance={
            "url": source_url,
            "imported_file": path.name,
            "note": note,
            "imported_at": datetime.now(UTC).isoformat(),
        },
    )
