# Minimal, production-grade Python base
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# Runtime system deps only; tzdata powers daily buckets.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates tzdata && \
    rm -rf /var/lib/apt/lists/*

# Install collector dependencies at image build time so startup stays deterministic.
COPY collector/requirements.txt /tmp/collector-requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/collector-requirements.txt && \
    rm -f /tmp/collector-requirements.txt

WORKDIR /workspace/llm_collector
COPY collector/ ./collector/
COPY snapshots/rollup_snapshots.py ./snapshots/rollup_snapshots.py
USER 1000:1000

# Expose the app port (informational)
EXPOSE 9000

CMD ["gunicorn", "--workers", "1", "--bind", "0.0.0.0:9000", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "collector.collector:app"]
