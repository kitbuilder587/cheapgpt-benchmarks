FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
COPY profiles ./profiles
COPY schemas ./schemas
COPY benchmarks.lock.yaml ./
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim-bookworm

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
WORKDIR /workspace
COPY --from=builder /app/.venv /app/.venv
ENTRYPOINT ["cheapgpt-benchmarks"]
CMD ["--help"]
