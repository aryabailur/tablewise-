# Tablewise API (FastAPI + LangGraph + Chroma). Built by docker-compose.yml at the repo root.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CHROMA_DIR=/app/data/chroma \
    FASTEMBED_CACHE_DIR=/app/data/fastembed_cache

WORKDIR /app

COPY requirements.txt .
# Postgres driver + Prometheus instrumentation are pinned in requirements.txt once it is
# re-exported from pyproject; the second install is a no-op then and a safety net until then.
RUN pip install -r requirements.txt \
 && pip install "psycopg[binary]>=3.2" "prometheus-fastapi-instrumentator>=7.0" "prometheus-client>=0.20"

COPY app ./app
COPY knowledge ./knowledge
COPY mcp_server.py docker-entrypoint.sh ./
RUN sed -i 's/\r$//' docker-entrypoint.sh && chmod +x docker-entrypoint.sh \
 && mkdir -p /app/data/chroma /app/data/fastembed_cache

VOLUME ["/app/data/chroma", "/app/data/fastembed_cache"]
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=120s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["./docker-entrypoint.sh"]
