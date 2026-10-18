# One container for Railway (or any Docker host): the FastAPI backend on $PORT plus the
# Photon family messenger on :8787 next to it. Lives at the repo root so Railway always detects it.
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY family-messenger/package.json family-messenger/package-lock.json family-messenger/
RUN cd family-messenger && npm ci --silent

COPY backend backend
COPY ml/__init__.py ml/scorer.py ml/
COPY family-messenger/src family-messenger/src
COPY family-messenger/tsconfig.json family-messenger/

ENV PHOTON_SIDECAR_URL=http://localhost:8787 PYTHONUNBUFFERED=1
CMD ["bash", "backend/deploy/start.sh"]
