# Build from repo root:
#   docker build -f backend/Dockerfile -t wardrivrr-api:latest .
FROM python:3.11-slim

ARG WARDRIVRR_VERSION=1.0.0
LABEL org.opencontainers.image.title="wardrivrr" \
      org.opencontainers.image.description="Local-first wardriving on OpenStreetMap" \
      org.opencontainers.image.version="${WARDRIVRR_VERSION}" \
      org.opencontainers.image.source="https://github.com/JAKAMI99/wardrivrr"

# docker CLI: API seeds/clips PBFs then recreates Valhalla via host docker.sock (car overlay).
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends \
    osm2pgsql \
    libpq-dev \
    gcc \
    curl \
    ca-certificates \
    && DOCKER_ARCH="$(uname -m)" \
    && case "${TARGETARCH:-}" in \
         amd64) DOCKER_ARCH=x86_64 ;; \
         arm64) DOCKER_ARCH=aarch64 ;; \
         arm) DOCKER_ARCH=armhf ;; \
       esac \
    && case "$DOCKER_ARCH" in \
         x86_64|aarch64|armhf) \
           curl -fsSL "https://download.docker.com/linux/static/stable/${DOCKER_ARCH}/docker-27.3.1.tgz" \
             | tar -xz --strip-components=1 -C /usr/local/bin docker/docker ;; \
         *) echo "WARN: no static docker CLI for $DOCKER_ARCH — Valhalla restart from API disabled" ;; \
       esac \
    && mkdir -p /usr/local/lib/docker/cli-plugins \
    && case "$DOCKER_ARCH" in \
         x86_64) COMPOSE_ARCH=x86_64 ;; \
         aarch64) COMPOSE_ARCH=aarch64 ;; \
         armhf) COMPOSE_ARCH=armv7 ;; \
         *) COMPOSE_ARCH="" ;; \
       esac \
    && if [ -n "$COMPOSE_ARCH" ]; then \
         curl -fsSL "https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-${COMPOSE_ARCH}" \
           -o /usr/local/lib/docker/cli-plugins/docker-compose \
         && chmod +x /usr/local/lib/docker/cli-plugins/docker-compose ; \
       fi \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend/ /app/backend/
COPY frontend/ /app/frontend/
COPY scripts/ /app/scripts/
COPY docker/ /app/docker/
COPY VERSION /app/VERSION

# Offline geo DBs: prefer volume + prepare-data at deploy time.
# Or bake in: RUN python /app/scripts/prepare_offline_data.py

WORKDIR /app/backend
ENV PYTHONUNBUFFERED=1
ENV WARDRIVRR_VERSION=${WARDRIVRR_VERSION}
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
