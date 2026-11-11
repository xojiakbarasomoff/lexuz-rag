# syntax=docker/dockerfile:1.7
FROM python:3.12.12-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra local-embeddings --no-install-project
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY evals ./evals
RUN uv sync --frozen --no-dev --extra local-embeddings

FROM python:3.12.12-slim-bookworm
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --home /app app \
    && mkdir -p /data/snapshots /data/models && chown -R app:app /data
WORKDIR /app
COPY --from=build --chown=app:app /app /app
COPY --chown=app:app frontend ./frontend
USER app
EXPOSE 8000
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
