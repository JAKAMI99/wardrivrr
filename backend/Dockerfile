# Build from repo root:
#   docker build -f backend/Dockerfile -t wardrivrr-api .
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    osm2pgsql \
    libpq-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend/ /app/backend/
COPY frontend/ /app/frontend/
COPY scripts/ /app/scripts/
COPY docker/ /app/docker/

# Offline geo DBs: prefer volume + prepare-data at deploy time.
# Or bake in: RUN python /app/scripts/prepare_offline_data.py

WORKDIR /app/backend
ENV PYTHONUNBUFFERED=1
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
