# Multi-stage build: compile the React frontend, then copy the static
# output into a slim Python runtime that also serves it. One image, one
# container, one process to deploy on the free-tier app instance.

# ---- Stage 1: build the frontend -------------------------------------
FROM node:22-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --quiet
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python runtime -------------------------------------
FROM python:3.12-slim AS runtime

# Pillow needs libjpeg/zlib at runtime; curl is used by the healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo \
    zlib1g \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY --from=frontend-build /frontend/dist ./frontend/dist

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /srv/backend/data \
    && chown -R appuser:appuser /srv
USER appuser

WORKDIR /srv/backend
ENV DATA_DIR=/srv/backend/data \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
