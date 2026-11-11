"""HTTP API: health, documents, ask, error codes, headers, Redis outage."""

import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from shutil import which

import pytest
from fastapi.testclient import TestClient

from app.ingestion import sources
from app.ingestion.pipeline import RawSource, ingest_source
from app.providers.embeddings import HashingEmbeddingProvider
from app.providers.llm import FakeLLMProvider
from tests.conftest import fixture_html
from tests.test_answer_integration import good_answer

KEY = "istemolchilar-huquqlari"


@pytest.fixture
def client(db, redis_client, monkeypatch, settings):
    import app.generation.answer as answer_mod
    from app.api.main import app
    from app.core.limits import Guards

    monkeypatch.setitem(sources.SOURCES, KEY, replace(sources.SOURCES[KEY], min_articles=3))
    emb = HashingEmbeddingProvider(settings)
    ingest_source(
        KEY,
        raw=RawSource(
            fixture_html("lexuz_consumer_excerpt.html").encode(),
            datetime(2026, 11, 11, 5, tzinfo=UTC),
            "local_import",
            {"url": "https://lex.uz/docs/-4704"},
        ),
        settings=settings,
        embedder=emb,
        now=datetime(2026, 11, 11, tzinfo=UTC),
    )
    monkeypatch.setattr(
        answer_mod,
        "_default_deps",
        answer_mod.Deps(settings, FakeLLMProvider(good_answer), emb, Guards(redis_client, settings)),
    )
    return TestClient(app)


@pytest.mark.integration
def test_health(client):
    assert client.get("/health/live").json() == {"status": "ok"}
    r = client.get("/health/ready")
    assert r.status_code == 200 and r.json()["checks"]["generation"] == "enabled"


@pytest.mark.integration
def test_documents(client):
    docs = client.get("/api/v1/documents").json()
    assert len(docs) == 1 and docs[0]["article_count"] == 6
    d = client.get(f"/api/v1/documents/{docs[0]['id']}").json()
    assert [a["label"] for a in d["articles"]][:5] == ["1", "2", "3", "4", "12¹"]
    assert d["source_kind"] == "local_import"
    assert client.get("/api/v1/documents/00000000-0000-0000-0000-000000000000").status_code == 404


@pytest.mark.integration
def test_ask_happy_path_shape_and_no_internal_leak(client):
    r = client.post("/api/v1/ask", json={"question": "Isteʼmolchi kim?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {
        "request_id",
        "status",
        "claims",
        "sources",
        "clarifying_question",
        "limitations",
        "corpus_checked_at",
        "latency_ms",
    }
    assert body["status"] == "answered" and body["sources"][0]["source_url"].startswith("https://lex.uz/")
    assert "untrusted" not in r.text and "<sources>" not in r.text  # no prompt/context leak
    assert r.headers["X-Request-ID"] == body["request_id"]
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]


@pytest.mark.integration
def test_ask_validation_errors(client):
    r = client.post("/api/v1/ask", json={"question": "x" * 601})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"
    assert client.post("/api/v1/ask", json={}).status_code == 422


@pytest.mark.integration
def test_rate_limit_returns_429(client, monkeypatch, settings):
    import app.api.main as main
    from app.core.limits import Guards, get_redis

    strict = settings.model_copy(update={"rate_limit_per_minute": 1})
    monkeypatch.setattr(main, "get_guards", lambda: Guards(get_redis(), strict))
    assert client.post("/api/v1/ask", json={"question": "Isteʼmolchi kim?"}).status_code == 200
    r = client.post("/api/v1/ask", json={"question": "Isteʼmolchi kim?"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited" and "Retry-After" in r.headers


@pytest.mark.integration
def test_redis_outage_disables_generation_but_not_catalog(client, monkeypatch, settings):
    import redis

    import app.api.main as main
    from app.core.limits import Guards

    dead = Guards(redis.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.2), settings)
    monkeypatch.setattr(main, "get_guards", lambda: dead)
    r = client.post("/api/v1/ask", json={"question": "Isteʼmolchi kim?"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "generation_unavailable"
    assert client.get("/api/v1/documents").status_code == 200
    ready = client.get("/health/ready").json()
    assert ready["checks"]["generation"] == "disabled"


FRONTEND = Path(__file__).parents[1] / "frontend" / "app.js"


def test_frontend_uses_no_html_sinks():
    src = FRONTEND.read_text(encoding="utf-8")
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert sink not in src, sink


@pytest.mark.skipif(which("node") is None, reason="node not installed")
def test_frontend_renders_malicious_text_as_text():
    script = Path(__file__).parent / "frontend_xss_test.js"
    out = subprocess.run(["node", str(script), str(FRONTEND)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr


def test_ui_shows_free_tier_privacy_notice():
    html = (Path(__file__).parents[1] / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "Shaxsiy yoki maxfiy" in html and "18 yoshdan" in html and "Gemini" in html
