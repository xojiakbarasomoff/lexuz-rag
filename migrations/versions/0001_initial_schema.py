"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-11 09:53:54.713050
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import pgvector.sqlalchemy

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
    op.create_table('chunk_embeddings',
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('embedding_space', sa.String(length=200), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('content_hash', 'embedding_space')
    )
    op.create_table('documents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('source_key', sa.String(length=64), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('official_id', sa.String(length=64), nullable=False),
    sa.Column('canonical_url', sa.Text(), nullable=False),
    sa.Column('language', sa.String(length=16), nullable=False),
    sa.Column('official_status', sa.Text(), nullable=True),
    sa.Column('doc_number', sa.String(length=64), nullable=True),
    sa.Column('adoption_date', sa.Date(), nullable=True),
    sa.Column('entry_into_force_date', sa.Date(), nullable=True),
    sa.Column('active_version_id', sa.UUID(), nullable=True),
    sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_check_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_key')
    )
    op.create_table('usage_events',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('model', sa.String(length=200), nullable=False),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('est_cost_usd', sa.Numeric(precision=12, scale=6), nullable=False),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('outcome', sa.String(length=32), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_usage_events_created_at'), 'usage_events', ['created_at'], unique=False)
    op.create_table('document_versions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('content_checksum', sa.String(length=64), nullable=False),
    sa.Column('raw_checksum', sa.String(length=64), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('source_kind', sa.String(length=32), nullable=False),
    sa.Column('source_revision_label', sa.String(length=64), nullable=True),
    sa.Column('raw_snapshot_path', sa.Text(), nullable=False),
    sa.Column('provenance', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('parser_version', sa.String(length=32), nullable=False),
    sa.Column('validation', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('article_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_id', 'content_checksum', name='uq_version_content')
    )
    op.create_index(op.f('ix_document_versions_document_id'), 'document_versions', ['document_id'], unique=False)
    op.create_foreign_key('fk_documents_active_version', 'documents', 'document_versions', ['active_version_id'], ['id'])
    op.create_table('ingestion_jobs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('trigger', sa.String(length=32), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('fetched_bytes', sa.Integer(), nullable=False),
    sa.Column('articles_parsed', sa.Integer(), nullable=False),
    sa.Column('chunks_indexed', sa.Integer(), nullable=False),
    sa.Column('embeddings_created', sa.Integer(), nullable=False),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('error_detail', sa.Text(), nullable=True),
    sa.Column('version_id', sa.UUID(), nullable=True),
    sa.Column('activated_version_id', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ingestion_jobs_document_id'), 'ingestion_jobs', ['document_id'], unique=False)
    op.create_index('uq_one_running_job_per_document', 'ingestion_jobs', ['document_id'], unique=True, postgresql_where=sa.text("status = 'running'"))
    op.create_table('articles',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('version_id', sa.UUID(), nullable=False),
    sa.Column('label', sa.String(length=32), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('heading_context', sa.Text(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('notes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('source_anchor', sa.String(length=64), nullable=True),
    sa.Column('source_url', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('future_effective', sa.Boolean(), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['version_id'], ['document_versions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('version_id', 'label', name='uq_article_label')
    )
    op.create_index(op.f('ix_articles_version_id'), 'articles', ['version_id'], unique=False)
    op.create_table('chunks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('article_id', sa.UUID(), nullable=False),
    sa.Column('version_id', sa.UUID(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('embed_text', sa.Text(), nullable=False),
    sa.Column('search_text', sa.Text(), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('char_len', sa.Integer(), nullable=False),
    sa.Column('est_tokens', sa.Integer(), nullable=False),
    sa.Column('tsv', postgresql.TSVECTOR(), sa.Computed("to_tsvector('simple', search_text)", persisted=True), nullable=False),
    sa.ForeignKeyConstraint(['article_id'], ['articles.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['version_id'], ['document_versions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_chunks_article_id'), 'chunks', ['article_id'], unique=False)
    op.create_index(op.f('ix_chunks_content_hash'), 'chunks', ['content_hash'], unique=False)
    op.create_index('ix_chunks_search_trgm', 'chunks', ['search_text'], unique=False, postgresql_using='gin', postgresql_ops={'search_text': 'gin_trgm_ops'})
    op.create_index('ix_chunks_tsv', 'chunks', ['tsv'], unique=False, postgresql_using='gin')
    op.create_index(op.f('ix_chunks_version_id'), 'chunks', ['version_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_chunks_version_id'), table_name='chunks')
    op.drop_index('ix_chunks_tsv', table_name='chunks', postgresql_using='gin')
    op.drop_index('ix_chunks_search_trgm', table_name='chunks', postgresql_using='gin', postgresql_ops={'search_text': 'gin_trgm_ops'})
    op.drop_index(op.f('ix_chunks_content_hash'), table_name='chunks')
    op.drop_index(op.f('ix_chunks_article_id'), table_name='chunks')
    op.drop_table('chunks')
    op.drop_index(op.f('ix_articles_version_id'), table_name='articles')
    op.drop_table('articles')
    op.drop_index('uq_one_running_job_per_document', table_name='ingestion_jobs', postgresql_where=sa.text("status = 'running'"))
    op.drop_index(op.f('ix_ingestion_jobs_document_id'), table_name='ingestion_jobs')
    op.drop_table('ingestion_jobs')
    op.drop_constraint('fk_documents_active_version', 'documents', type_='foreignkey')
    op.drop_index(op.f('ix_document_versions_document_id'), table_name='document_versions')
    op.drop_table('document_versions')
    op.drop_index(op.f('ix_usage_events_created_at'), table_name='usage_events')
    op.drop_table('usage_events')
    op.drop_table('documents')
    op.drop_table('chunk_embeddings')
