from __future__ import annotations

from app.core.logging import get_logger
from app.ingestion.pipeline import JobAlreadyRunning, ingest_source
from app.ingestion.sources import SOURCES
from app.tasks.celery_app import celery_app

log = get_logger(__name__)


@celery_app.task(name="lexuz.ingest_source", bind=True, max_retries=2, default_retry_delay=600)
def ingest_source_task(self, source_key: str, trigger: str = "schedule") -> dict:
    try:
        res = ingest_source(source_key, trigger=trigger)
    except JobAlreadyRunning:
        log.info("ingest_skipped_running", source=source_key)
        return {"source": source_key, "status": "skipped"}
    if res.status == "failed" and (res.error_code or "").startswith("fetch_"):
        # Transient source problem: retry later. Same content -> no new version, no new embeddings.
        raise self.retry()
    return {"source": source_key, "status": res.status, "version_id": str(res.version_id or "")}


@celery_app.task(name="lexuz.check_all_sources")
def check_all_sources() -> list[str]:
    for key in SOURCES:
        ingest_source_task.delay(key, trigger="schedule")
    return list(SOURCES)
