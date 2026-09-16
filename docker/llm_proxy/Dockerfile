FROM ghcr.io/astral-sh/uv:0.12.15 AS uv

FROM python:3.14-slim AS builder

WORKDIR /app

COPY --from=uv /uv /bin/uv
COPY pyproject.toml uv.lock ./
COPY src/ src/
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.14-slim

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 4141

CMD ["uvicorn", "llm_proxy.main:app", "--host", "0.0.0.0", "--port", "4141"]
