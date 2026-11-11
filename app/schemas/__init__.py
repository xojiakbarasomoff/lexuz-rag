from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.config import get_settings

# API-level status. The LLM output schema still has only the first three;
# "provider_blocked" is set by the backend when the provider's safety filter
# blocked the request/answer — a different situation from missing sources.
AnswerStatus = Literal["answered", "insufficient_evidence", "clarification_needed", "provider_blocked"]


class AskRequest(BaseModel):
    question: str = Field(min_length=3, description="One self-contained question in Uzbek")
    document_ids: list[uuid.UUID] | None = Field(default=None, max_length=5)

    @field_validator("question")
    @classmethod
    def _limit(cls, v: str) -> str:
        v = v.strip()
        limit = get_settings().max_question_chars
        if len(v) > limit:
            raise ValueError(f"question longer than {limit} characters")
        if len(v) < 3:
            raise ValueError("question too short")
        return v


class Claim(BaseModel):
    text: str
    source_ids: list[str]


class Source(BaseModel):
    """Built only from trusted database metadata — never from model output."""

    source_id: str
    document_id: uuid.UUID
    document_title: str
    article_label: str
    article_title: str
    excerpt: str = Field(description="Short excerpt copied from the stored original text")
    source_url: str
    version_id: uuid.UUID
    checked_at: datetime | None = Field(description="When this index last verified the source; NOT an effective date")
    has_future_amendment_note: bool = False


class AskResponse(BaseModel):
    request_id: str
    status: AnswerStatus
    claims: list[Claim] = []
    sources: list[Source] = []
    clarifying_question: str | None = None
    limitations: list[str] = []
    corpus_checked_at: datetime | None = None
    latency_ms: int


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    request_id: str
    error: ErrorBody


class DocumentSummary(BaseModel):
    id: uuid.UUID
    title: str
    canonical_url: str
    language: str
    official_status: str | None
    doc_number: str | None
    adoption_date: date | None = Field(description="Date printed by the source for the document")
    entry_into_force_date: date | None = Field(description="Entry-into-force date printed by the source")
    last_checked_at: datetime | None = Field(description="Last successful check by this index")
    active_version_id: uuid.UUID | None
    source_revision_label: str | None = Field(description="Latest edition label shown on the source page")
    article_count: int


class ArticleSummary(BaseModel):
    id: uuid.UUID
    label: str
    title: str
    heading_context: str
    source_url: str
    status: str


class DocumentDetail(DocumentSummary):
    source_kind: str | None
    articles: list[ArticleSummary]
