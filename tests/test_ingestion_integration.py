"""Ingestion against real PostgreSQL + pgvector (no network)."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.ingestion import pipeline, sources
from app.ingestion.pipeline import JobAlreadyRunning, RawSource, ingest_source
from app.models import Chunk, ChunkEmbedding, Document, DocumentVersion, IngestionJob
from app.providers.embeddings import HashingEmbeddingProvider
from tests.conftest import fixture_html

pytestmark = pytest.mark.integration
KEY = "istemolchilar-huquqlari"


@pytest.fixture
def small_source(monkeypatch):
    spec = replace(sources.SOURCES[KEY], min_articles=3)
    monkeypatch.setitem(sources.SOURCES, KEY, spec)
    return spec


class CountingEmbedder(HashingEmbeddingProvider):
    def __init__(self, settings):
        super().__init__(settings)
        self.embedded = 0

    def embed_documents(self, texts):
        self.embedded += len(texts)
        return super().embed_documents(texts)


def raw(html: str, when="2026-11-11T05:00:00+00:00") -> RawSource:
    return RawSource(body=html.encode(), fetched_at=datetime.fromisoformat(when), source_kind="local_import",
                     provenance={"url": "https://lex.uz/docs/-4704", "note": "test fixture"})


def run(html, settings, embedder, **kw):
    return ingest_source(KEY, raw=raw(html, **kw), settings=settings, embedder=embedder,
                         now=datetime(2026, 11, 11, tzinfo=UTC))


def _active(s):
    from app.db.session import get_sessionmaker

    with get_sessionmaker()() as ss:
        d = ss.scalar(select(Document).where(Document.source_key == KEY))
        return d, ss.scalars(select(DocumentVersion).where(DocumentVersion.document_id == d.id)).all()


def test_first_ingest_activates_with_provenance(db, small_source, settings):
    emb = CountingEmbedder(settings)
    res = run(fixture_html("lexuz_consumer_excerpt.html"), settings, emb)
    assert res.status == "succeeded"
    doc, versions = _active(None)
    assert doc.active_version_id == res.version_id
    v = versions[0]
    assert v.status == "active" and v.source_kind == "local_import"
    assert v.raw_checksum and v.raw_snapshot_path.endswith(".html.gz")
    assert v.provenance["url"] == "https://lex.uz/docs/-4704"
    assert doc.entry_into_force_date.isoformat() == "1996-05-17"
    assert emb.embedded > 0


def test_reingest_same_content_is_idempotent(db, small_source, settings):
    emb = CountingEmbedder(settings)
    html = fixture_html("lexuz_consumer_excerpt.html")
    first = run(html, settings, emb)
    n = emb.embedded
    second = run(html, settings, emb, when="2026-11-12T05:00:00+00:00")
    assert second.status == "unchanged" and second.version_id == first.version_id
    assert emb.embedded == n  # no re-embedding
    doc, versions = _active(None)
    assert len(versions) == 1
    assert doc.last_checked_at.isoformat().startswith("2026-11-12")


def test_changed_article_creates_new_version_and_reuses_unchanged_vectors(db, small_source, settings):
    emb = CountingEmbedder(settings)
    html = fixture_html("lexuz_consumer_excerpt.html")
    first = run(html, settings, emb)
    n_first = emb.embedded
    changed = html.replace("shu niyatda boʻlgan fuqaro", "shu niyatda boʻlgan fuqaro (TEST TAHRIR)")
    assert changed != html
    second = run(changed, settings, emb)
    assert second.status == "succeeded" and second.version_id != first.version_id
    assert 0 < emb.embedded - n_first < n_first  # only the changed chunk(s) were embedded
    doc, versions = _active(None)
    status = {v.id: v.status for v in versions}
    assert status[first.version_id] == "superseded" and status[second.version_id] == "active"
    assert doc.active_version_id == second.version_id


def test_removed_article_leaves_active_index(db, small_source, settings):
    from app.db.session import get_sessionmaker
    from app.retrieval.search import retrieve

    emb = CountingEmbedder(settings)
    html = fixture_html("lexuz_consumer_excerpt.html")
    run(html, settings, emb)
    start = html.index('<div class="CLAUSE_DEFAULT lx_elem" onmousemove="lx_mo(event,-7674463)"')
    end = html.index('<div class="CLAUSE_DEFAULT', start + 10)
    without_121 = html[:start] + html[end:]
    res = run(without_121, settings, emb)
    assert res.status == "needs_review"  # 1 of 6 articles vanished (> 10%) -> human check first
    pipeline.approve_version(res.version_id, emb.space)
    with get_sessionmaker()() as s:
        res = retrieve(s, "12¹-modda tovarni topshirish muddati", settings, emb)
    assert "12¹" not in [a.label for a in res.articles]


def test_broken_parse_keeps_previous_active_version(db, small_source, settings):
    emb = CountingEmbedder(settings)
    good = run(fixture_html("lexuz_consumer_excerpt.html"), settings, emb)
    bad = run("<html><body><h1>Sayt texnik ishlar sababli yopiq</h1></body></html>", settings, emb)
    assert bad.status == "failed" and bad.error_code == "validation_failed"
    doc, versions = _active(None)
    assert doc.active_version_id == good.version_id
    assert "validation_failed" in doc.last_check_error
    assert {v.status for v in versions} == {"active", "rejected"}


def test_future_amendment_requires_manual_review_synthetic(db, small_source, settings):
    """Synthetic future-effective note: version is indexed but NOT activated."""
    emb = CountingEmbedder(settings)
    good = run(fixture_html("lexuz_consumer_excerpt.html"), settings, emb)
    future = fixture_html("lexuz_consumer_excerpt.html").replace(
        "Kuchga kirish sanasi — 2025-yil 2-noyabr", "Kuchga kirish sanasi — 2027-yil 1-yanvar")
    res = run(future, settings, emb)
    assert res.status == "needs_review"
    doc, _ = _active(None)
    assert doc.active_version_id == good.version_id
    pipeline.approve_version(res.version_id, emb.space)
    doc, _ = _active(None)
    assert doc.active_version_id == res.version_id


def test_one_running_job_per_document(db, small_source, settings):
    from app.db.session import session_scope

    doc_id = pipeline.ensure_document(small_source)
    with session_scope() as s:
        s.add(IngestionJob(document_id=doc_id, status="running"))
    with pytest.raises(JobAlreadyRunning):
        run(fixture_html("lexuz_consumer_excerpt.html"), settings, CountingEmbedder(settings))


def test_old_version_never_in_default_retrieval(db, small_source, settings):
    from app.db.session import get_sessionmaker
    from app.retrieval.search import retrieve

    emb = CountingEmbedder(settings)
    html = fixture_html("lexuz_consumer_excerpt.html")
    first = run(html, settings, emb)
    second = run(html.replace("fuqaro (jismoniy shaxs)", "fuqaro (jismoniy shaxs) YANGI"), settings, emb)
    with get_sessionmaker()() as s:
        res = retrieve(s, "isteʼmolchi tushunchasi fuqaro jismoniy shaxs", settings, emb)
        versions = {a.version_id for a in res.articles}
        assert versions == {second.version_id}
        assert first.version_id not in versions
        # both versions' chunks still exist for audit
        assert s.scalar(select(func.count()).select_from(Chunk).where(Chunk.version_id == first.version_id)) > 0


def test_vectors_are_scoped_by_embedding_space(db, small_source, settings):
    from app.db.session import get_sessionmaker
    from app.retrieval.search import retrieve

    emb = CountingEmbedder(settings)
    run(fixture_html("lexuz_consumer_excerpt.html"), settings, emb)
    other = CountingEmbedder(settings)
    other.space = "other:model:64"
    with get_sessionmaker()() as s:
        assert s.scalar(select(func.count()).select_from(ChunkEmbedding)
                        .where(ChunkEmbedding.embedding_space == other.space)) == 0
        res = retrieve(s, "zzzzqqq", settings, other)  # no vectors in this space, no lexical hit
    assert res.articles == []
