# Minimal, production-grade Python base
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# Runtime system deps only; tzdata powers daily buckets.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates tzdata && \
    rm -rf /var/lib/apt/lists/*

# Install collector dependencies at image build time so startup stays deterministic.
COPY collector/requirements.txt /tmp/collector-requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /tmp/collector-requirements.txt && \
    rm -f /tmp/collector-requirements.txt

# Create a workspace where your host folder will be mounted
WORKDIR /workspace/llm_collector

# Expose the app port (informational)
EXPOSE 9000

# Default command assumes:
#  - your host volume is mounted at /workspace/llm_collector
#  - Python module path is the repo root, with app at collector/collector.py exposing `app`
CMD ["/bin/sh", "-lc", "\
    mkdir -p snapshots; \
    exec gunicorn \
      --chdir /workspace/llm_collector \
      --workers 1 \
      --bind 0.0.0.0:9000 \
      --timeout 120 \
      --access-logfile - \
      --error-logfile - \
      collector.collector:app \
  "]
