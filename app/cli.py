"""Operator CLI: `python -m app.cli <command>` (alias `lexuz` inside the image).

Ingestion is never exposed through the public HTTP API.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def cmd_sources(_args) -> int:
    from app.ingestion.sources import SOURCES

    _print([{"key": s.key, "url": s.url, "language": s.language} for s in SOURCES.values()])
    return 0


def cmd_ingest(args) -> int:
    from app.ingestion.pipeline import JobAlreadyRunning, ingest_source, load_local_file
    from app.ingestion.sources import SOURCES, get_source

    keys = list(SOURCES) if args.source == "all" else [args.source]
    raw = None
    if args.from_file:
        if len(keys) != 1:
            print("--from-file needs exactly one source", file=sys.stderr)
            return 2
        spec = get_source(keys[0])
        if args.source_url != spec.url:
            print(f"--source-url must be the approved URL {spec.url}", file=sys.stderr)
            return 2
        raw = load_local_file(
            Path(args.from_file),
            source_url=args.source_url,
            retrieved_at=datetime.fromisoformat(args.retrieved_at).astimezone(UTC),
            note=args.note or "",
        )
    rc = 0
    for key in keys:
        try:
            res = ingest_source(key, trigger="cli", raw=raw)
            _print(
                {
                    "source": key,
                    "job_id": res.job_id,
                    "status": res.status,
                    "version_id": res.version_id,
                    "error_code": res.error_code,
                    "detail": res.detail,
                }
            )
            rc |= 0 if res.status in ("succeeded", "unchanged") else 1
        except JobAlreadyRunning:
            _print({"source": key, "status": "skipped", "reason": "another job is running"})
            rc |= 1
    return rc


def cmd_status(_args) -> int:
    from app.db.session import session_scope
    from app.models import Document, DocumentVersion, IngestionJob

    out = []
    with session_scope() as s:
        for d in s.scalars(select(Document).order_by(Document.source_key)):
            versions = s.scalars(
                select(DocumentVersion)
                .where(DocumentVersion.document_id == d.id)
                .order_by(DocumentVersion.created_at.desc())
                .limit(5)
            ).all()
            jobs = s.scalars(
                select(IngestionJob)
                .where(IngestionJob.document_id == d.id)
                .order_by(IngestionJob.started_at.desc())
                .limit(5)
            ).all()
            out.append(
                {
                    "source_key": d.source_key,
                    "title": d.title,
                    "active_version_id": d.active_version_id,
                    "last_checked_at": d.last_checked_at,
                    "last_check_error": d.last_check_error,
                    "versions": [
                        {
                            "id": v.id,
                            "status": v.status,
                            "fetched_at": v.fetched_at,
                            "kind": v.source_kind,
                            "revision_label": v.source_revision_label,
                            "articles": v.article_count,
                            "validation": v.validation.get("outcome"),
                        }
                        for v in versions
                    ],
                    "jobs": [
                        {
                            "id": j.id,
                            "status": j.status,
                            "started_at": j.started_at,
                            "finished_at": j.finished_at,
                            "articles": j.articles_parsed,
                            "chunks": j.chunks_indexed,
                            "embeddings_created": j.embeddings_created,
                            "error_code": j.error_code,
                        }
                        for j in jobs
                    ],
                }
            )
    _print(out)
    return 0


def cmd_show_version(args) -> int:
    from app.db.session import session_scope
    from app.models import DocumentVersion

    with session_scope() as s:
        v = s.get(DocumentVersion, uuid.UUID(args.version_id))
        if not v:
            print("not found", file=sys.stderr)
            return 1
        _print(
            {
                "id": v.id,
                "status": v.status,
                "validation": v.validation,
                "provenance": v.provenance,
                "snapshot": v.raw_snapshot_path,
                "raw_checksum": v.raw_checksum,
                "content_checksum": v.content_checksum,
            }
        )
    return 0


def cmd_approve(args) -> int:
    from app.ingestion.pipeline import approve_version

    approve_version(uuid.UUID(args.version_id), get_settings().embedding_space)
    _print({"approved": args.version_id})
    return 0


def cmd_reindex(_args) -> int:
    """Embed every stored version for the *current* EMBEDDING_* settings.

    Run this before switching the API to a new embedding model; vectors of the
    old space are kept until deleted, and never mixed with the new ones.
    """
    from app.db.session import session_scope
    from app.ingestion.pipeline import embed_missing_for_version
    from app.models import DocumentVersion, VersionStatus
    from app.providers.embeddings import get_embedding_provider

    embedder = get_embedding_provider(get_settings())
    with session_scope() as s:
        ids = s.scalars(
            select(DocumentVersion.id).where(
                DocumentVersion.status.in_([VersionStatus.ACTIVE, VersionStatus.INDEXED, VersionStatus.NEEDS_REVIEW])
            )
        ).all()
    total = sum(embed_missing_for_version(i, embedder) for i in ids)
    _print({"embedding_space": embedder.space, "versions": len(ids), "embeddings_created": total})
    return 0


def cmd_ask(args) -> int:
    from app.api.errors import error_payload
    from app.generation.answer import AnswerError, answer_question

    try:
        res = answer_question(args.question, document_ids=None, request_id="cli")
    except AnswerError as exc:
        _print(error_payload(exc.code, "cli")[1])
        return 1
    _print(res.model_dump(mode="json"))
    return 0


def cmd_eval(args) -> int:
    from evals.run import main as eval_main

    return eval_main(args.eval_args)


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    p = argparse.ArgumentParser(prog="lexuz")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sources", help="list pre-approved sources").set_defaults(fn=cmd_sources)
    ing = sub.add_parser("ingest", help="fetch/parse/index a source (or 'all')")
    ing.add_argument("source")
    ing.add_argument("--from-file", help="import a file downloaded from the official source")
    ing.add_argument("--source-url", help="approved URL the file was downloaded from")
    ing.add_argument("--retrieved-at", help="ISO timestamp of the download, e.g. 2026-11-11T10:00:00+05:00")
    ing.add_argument("--note")
    ing.set_defaults(fn=cmd_ingest)
    sub.add_parser("status", help="documents, versions and recent jobs").set_defaults(fn=cmd_status)
    sv = sub.add_parser("show-version")
    sv.add_argument("version_id")
    sv.set_defaults(fn=cmd_show_version)
    ap = sub.add_parser("approve-version", help="activate a needs_review version after manual review")
    ap.add_argument("version_id")
    ap.set_defaults(fn=cmd_approve)
    sub.add_parser("reindex-embeddings", help="embed stored versions for the current embedding space").set_defaults(
        fn=cmd_reindex
    )
    ask = sub.add_parser("ask", help="answer one question locally (uses the configured LLM)")
    ask.add_argument("question")
    ask.set_defaults(fn=cmd_ask)
    ev = sub.add_parser("eval", help="run evaluations (see evals/README.md)")
    ev.add_argument("eval_args", nargs=argparse.REMAINDER)
    ev.set_defaults(fn=cmd_eval)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
