"""Test setup.

Integration tests run against a real PostgreSQL + pgvector and Redis (the
docker compose services locally, service containers in CI). Lex.uz and the AI
provider are never contacted: fixtures are local files and the LLM is a fake.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://lexuz:lexuz@127.0.0.1:55442/lexuz_test")
TEST_REDIS = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:56379/15")
os.environ.update(
    APP_ENV="test",
    DATABASE_URL=TEST_DB,
    REDIS_URL=TEST_REDIS,
    EMBEDDING_PROVIDER="hashing",
    EMBEDDING_MODEL="test-hashing",
    EMBEDDING_DIM="64",
    LLM_PROVIDER="fake",
    SNAPSHOT_DIR=tempfile.mkdtemp(prefix="lexuz-snap-"),
    SERVE_FRONTEND="false",
    FETCH_MIN_INTERVAL_S="0",
    RATE_LIMIT_PER_MINUTE="1000",
    RATE_LIMIT_PER_DAY="100000",
)

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _ensure_database() -> None:
    from sqlalchemy.engine import make_url

    url = make_url(TEST_DB)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        if not c.scalar(text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": url.database}):
            c.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def migrated_db():
    from alembic import command
    from alembic.config import Config

    _ensure_database()
    cfg = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture
def db(migrated_db):
    from app.db.session import get_engine

    with get_engine().begin() as c:
        c.execute(
            text(
                "TRUNCATE usage_events, ingestion_jobs, chunk_embeddings, chunks, articles, "
                "document_versions, documents RESTART IDENTITY CASCADE"
            )
        )
    yield


@pytest.fixture
def redis_client():
    from app.core.limits import get_redis

    r = get_redis()
    r.flushdb()
    yield r
    r.flushdb()


@pytest.fixture
def settings():
    from app.core.config import get_settings

    return get_settings()
