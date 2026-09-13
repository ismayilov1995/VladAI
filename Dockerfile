# No `# syntax=` directive on purpose: it makes every build pull a frontend
# image from Docker Hub first, and nothing here needs a feature the builder
# does not already have. Please leave it off unless you add syntax that needs it.

# ---------------------------------------------------------------------------
# Stage 1: build the frontend.
# Vite writes to ../backend/static, so the paths here mirror the repo layout
# and the built assets land where the Python stage expects them.
# ---------------------------------------------------------------------------
FROM node:20-alpine AS frontend

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# ---------------------------------------------------------------------------
# Stage 2: the runtime. FastAPI serves the API and the built frontend.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/mosaic_fill/ ./mosaic_fill/
COPY backend/app/ ./app/
COPY backend/libraries/ ./libraries/
COPY --from=frontend /app/backend/static/ ./static/

# Uploads are transient files in a writable temp dir; there is no database.
ENV VLADA_UPLOAD_DIR=/tmp/vlada-uploads \
    VLADA_LIBRARY_DIR=/app/libraries \
    VLADA_STATIC_DIR=/app/static

RUN useradd --create-home --uid 10001 vlada \
    && mkdir -p /tmp/vlada-uploads \
    && chown -R vlada:vlada /app /tmp/vlada-uploads
USER vlada

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
