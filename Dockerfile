# syntax=docker/dockerfile:1
ARG PYTHON_VERSION=3.13

FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev --group test

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY tests ./tests
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --group test


FROM python:${PYTHON_VERSION}-slim-bookworm AS runner

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

COPY --from=builder /app /app

EXPOSE 8000
