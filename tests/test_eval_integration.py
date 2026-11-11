"""The live answer eval must never exceed --max-cost-usd (checked with a fake provider)."""

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.ingestion import sources
from app.ingestion.pipeline import RawSource, ingest_source
from app.providers.embeddings import HashingEmbeddingProvider
from app.providers.llm import FakeLLMProvider
from tests.conftest import fixture_html

pytestmark = pytest.mark.integration
KEY = "istemolchilar-huquqlari"


@pytest.fixture
def eval_env(db, redis_client, monkeypatch, settings, tmp_path):
    import evals.run as run

    monkeypatch.setitem(sources.SOURCES, KEY, replace(sources.SOURCES[KEY], min_articles=3))
    ingest_source(
        KEY,
        raw=RawSource(
            fixture_html("lexuz_consumer_excerpt.html").encode(),
            datetime(2026, 11, 11, 5, tzinfo=UTC),
            "local_import",
            {"url": "https://lex.uz/docs/-4704"},
        ),
        settings=settings,
        embedder=HashingEmbeddingProvider(settings),
        now=datetime(2026, 11, 11, tzinfo=UTC),
    )
    real_like = settings.model_copy(update={"llm_provider": "anthropic"})
    monkeypatch.setattr(run, "get_settings", lambda: real_like)
    monkeypatch.setattr(run, "RESULTS", tmp_path)
    llm = FakeLLMProvider(model="fake-but-counted")
    monkeypatch.setattr("app.providers.llm.get_llm_provider", lambda s: llm)
    return run, llm, tmp_path


def test_cost_cap_blocks_calls_before_they_are_sent(eval_env):
    run, llm, out = eval_env
    assert run.main(["answers", "--split", "dev", "--max-cost-usd", "0.0001"]) == 0
    assert llm.calls == []  # nothing sent: the first worst-case reservation was refused
    report = json.loads(next(out.glob("*_answers_dev.json")).read_text(encoding="utf-8"))
    assert report["summary"]["not_run_due_to_cap"] == 30


def test_holdout_requires_explicit_confirmation(eval_env):
    run, llm, _ = eval_env
    assert run.main(["answers", "--split", "holdout"]) == 2
    assert llm.calls == []


def test_full_dev_run_writes_report_with_failure_sections(eval_env):
    run, llm, out = eval_env
    assert run.main(["answers", "--split", "dev", "--max-cost-usd", "1.0"]) == 0
    assert len(llm.calls) == 30  # fake always abstains -> one call per item, no repair
    md = next(out.glob("*_answers_dev.md")).read_text(encoding="utf-8")
    for section in ("Status errors - full detail", "Needed a repair call", "Not run (cost cap)"):
        assert section in md
    report = json.loads(next(out.glob("*_answers_dev.json")).read_text(encoding="utf-8"))
    st = report["summary"]["budget_state"]
    assert st["reserved_usd"] == 0 and st["spent_usd"] <= 1.0
