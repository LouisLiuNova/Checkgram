# syntax=docker/dockerfile:1

FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.9.24 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY checkgram ./checkgram
RUN uv sync --frozen --no-dev --no-editable


FROM python:3.13-slim

RUN groupadd --system --gid 10001 checkgram \
    && useradd --system --uid 10001 --gid 10001 --no-create-home checkgram \
    && mkdir --mode=0700 /data \
    && chown 10001:10001 /data

COPY --from=builder --chown=10001:10001 /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER 10001:10001
WORKDIR /app

ENTRYPOINT ["checkgram"]
CMD ["serve", "--config", "/config/config.toml", "--data-dir", "/data"]
