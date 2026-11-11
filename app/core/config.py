"""Application settings.

Every model name, price, limit and size is configurable through environment
variables (see `.env.example`). Prices are used only to compute *estimated*
cost; the provider's invoice is the source of truth.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- runtime ---------------------------------------------------------
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    # Raw questions/answers are never logged unless this is explicitly enabled
    # (development only; refused in production).
    log_question_text: bool = False

    database_url: str = "postgresql+psycopg://lexuz:lexuz@localhost:5432/lexuz"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str | None = None  # defaults to redis_url

    snapshot_dir: Path = Path("./data/snapshots")
    model_cache_dir: Path = Path("./data/models")

    # --- HTTP API --------------------------------------------------------
    cors_origins: list[str] = Field(default_factory=list)
    enable_api_docs: bool = True
    serve_frontend: bool = True
    frontend_dir: Path = Path("./frontend")
    metrics_token: str | None = None  # required to read /internal/metrics when set

    # --- Lex.uz fetching -------------------------------------------------
    fetch_allowed_hosts: list[str] = Field(default_factory=lambda: ["lex.uz", "www.lex.uz"])
    fetch_timeout_s: float = 60.0
    fetch_max_retries: int = 3
    fetch_backoff_base_s: float = 5.0
    fetch_min_interval_s: float = 10.0
    fetch_max_bytes: int = 30_000_000
    fetch_user_agent: str = "LexUZ-RAG/0.1 (non-commercial legal-information demo; low-frequency fetch)"

    # --- chunking --------------------------------------------------------
    chunk_max_chars: int = 1400
    chunk_overlap_paragraphs: int = 1
    chunk_overlap_max_chars: int = 300

    # --- embeddings ------------------------------------------------------
    embedding_provider: Literal["fastembed", "hashing"] = "fastembed"
    embedding_model: str = "intfloat/multilingual-e5-large"
    embedding_dim: int = 1024
    # Model-specific prefixes, taken from the model card (e5: "query: " / "passage: ").
    embedding_query_prefix: str = "query: "
    embedding_document_prefix: str = "passage: "
    embedding_batch_size: int = 16
    embedding_price_per_mtok_usd: float = 0.0  # local model -> no API cost

    # --- retrieval -------------------------------------------------------
    retrieval_candidate_limit: int = 40
    retrieval_top_k: int = 6
    retrieval_rrf_k: int = 60
    # Weighted RRF (tuned on the dev split only, see docs/evaluation.md)
    retrieval_semantic_weight: float = 1.0
    retrieval_lexical_weight: float = 0.25
    retrieval_article_ref_weight: float = 2.0
    retrieval_title_list: bool = False  # extra RRF list on article titles; off: made dev recall worse (decisions.md)
    context_max_tokens: int = 6000
    max_question_chars: int = 600

    # --- generation ------------------------------------------------------
    llm_provider: Literal["anthropic", "fake"] = "anthropic"
    llm_model: str = "claude-opus-5-5"
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    llm_max_output_tokens: int = 4096
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 1
    # Server-side refusal fallback ("default" lets the API pick the fallback model).
    llm_refusal_fallback: Literal["default", "off"] = "default"
    llm_input_price_per_mtok_usd: float = 4.0
    llm_output_price_per_mtok_usd: float = 20.0

    # --- public demo limits ---------------------------------------------
    rate_limit_per_minute: int = 5
    rate_limit_per_day: int = 40
    max_concurrent_llm_calls: int = 4
    llm_slot_ttl_s: int = 180
    daily_ai_budget_usd: float = 3.0
    daily_ingestion_budget_usd: float = 1.0
    budget_reservation_ttl_s: int = 300
    trusted_proxy_ips: list[str] = Field(default_factory=lambda: ["127.0.0.1"])

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.app_env == "production":
            if self.llm_provider == "fake":
                raise ValueError("LLM_PROVIDER=fake is not allowed in production")
            if self.embedding_provider == "hashing":
                raise ValueError("EMBEDDING_PROVIDER=hashing is a test stub; not allowed in production")
            if self.log_question_text:
                raise ValueError("LOG_QUESTION_TEXT must be false in production")
        return self

    @property
    def embedding_space(self) -> str:
        """Identifier of the vector space. Vectors from different spaces are never mixed."""
        return f"{self.embedding_provider}:{self.embedding_model}:{self.embedding_dim}"

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
