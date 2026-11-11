"""ORM models.

Version model (see docs/architecture.md):
  Document 1─* DocumentVersion 1─* Article 1─* Chunk ─(content_hash, space)→ ChunkEmbedding
Only `Document.active_version_id` is visible to default retrieval. Switching it
is a single-row UPDATE inside one transaction, so activation is atomic.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class VersionStatus:
    PARSED = "parsed"
    INDEXED = "indexed"  # chunks + embeddings ready, not yet active
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"  # validation failed
    NEEDS_REVIEW = "needs_review"  # parser not confident; manual approval required


class JobStatus:
    RUNNING = "running"
    SUCCEEDED = "succeeded"  # new version activated
    UNCHANGED = "unchanged"  # content identical to active version
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    source_key: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(Text)
    official_id: Mapped[str] = mapped_column(String(64))  # Lex.uz document id, e.g. "-6257288"
    canonical_url: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(16))  # BCP-47, e.g. "uz-Latn"
    official_status: Mapped[str | None] = mapped_column(Text)  # only if the source states it
    doc_number: Mapped[str | None] = mapped_column(String(64))
    adoption_date: Mapped[date | None] = mapped_column(Date)
    entry_into_force_date: Mapped[date | None] = mapped_column(Date)
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id", use_alter=True, name="fk_documents_active_version")
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_check_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    active_version: Mapped[DocumentVersion | None] = relationship(foreign_keys=[active_version_id], post_update=True)


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "content_checksum", name="uq_version_content"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    content_checksum: Mapped[str] = mapped_column(String(64))
    raw_checksum: Mapped[str] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_kind: Mapped[str] = mapped_column(String(32))  # live_fetch | local_import
    source_revision_label: Mapped[str | None] = mapped_column(String(64))  # as printed by the source
    raw_snapshot_path: Mapped[str] = mapped_column(Text)
    provenance: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(32))
    parser_version: Mapped[str] = mapped_column(String(32))
    validation: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    article_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped[Document] = relationship(foreign_keys=[document_id])


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("version_id", "label", name="uq_article_label"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(32))  # "12", "12¹" — never an integer
    ordinal: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    heading_context: Mapped[str] = mapped_column(Text, default="")
    text: Mapped[str] = mapped_column(Text)
    notes: Mapped[list] = mapped_column(JSONB, default=list)  # amendment notes printed by the source
    source_anchor: Mapped[str | None] = mapped_column(String(64))
    source_url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="in_force")  # in_force | repealed
    future_effective: Mapped[bool] = mapped_column(Boolean, default=False)
    content_hash: Mapped[str] = mapped_column(String(64))

    version: Mapped[DocumentVersion] = relationship()


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_chunks_search_trgm",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)  # original text of this part of the article
    embed_text: Mapped[str] = mapped_column(Text)  # header (doc, article, chapter) + text
    search_text: Mapped[str] = mapped_column(Text)  # normalized for lexical search
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    char_len: Mapped[int] = mapped_column(Integer)
    est_tokens: Mapped[int] = mapped_column(Integer)
    tsv: Mapped[str] = mapped_column(TSVECTOR, Computed("to_tsvector('simple', search_text)", persisted=True))

    article: Mapped[Article] = relationship()


class ChunkEmbedding(Base):
    """Embeddings keyed by content hash + vector space.

    Unchanged text is never re-embedded (the hash already has a row), and a
    query in space A can never be compared with vectors from space B.
    """

    __tablename__ = "chunk_embeddings"

    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    embedding_space: Mapped[str] = mapped_column(String(200), primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(Vector())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        # At most one running job per document (DB-enforced).
        Index(
            "uq_one_running_job_per_document",
            "document_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32))
    trigger: Mapped[str] = mapped_column(String(32), default="cli")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_bytes: Mapped[int] = mapped_column(Integer, default=0)
    articles_parsed: Mapped[int] = mapped_column(Integer, default=0)
    chunks_indexed: Mapped[int] = mapped_column(Integer, default=0)
    embeddings_created: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_detail: Mapped[str | None] = mapped_column(Text)
    version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    activated_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class UsageEvent(Base):
    """Estimated AI usage, for monitoring. Not an invoice."""

    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # ask_llm | query_embedding | ingestion_embedding
    model: Mapped[str] = mapped_column(String(200))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    est_cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), default=0)
    request_id: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(32))
