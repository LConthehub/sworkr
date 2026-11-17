# Sworkr in one image: the pages are built, then served by the same program as the API, on port 8008.
# This is what docker-compose.yml runs, and what gets published as the ready-made image.
#
#   docker build -t sworkr .

# ---- the pages ----
FROM node:20-alpine AS pages
WORKDIR /pages
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY frontend/ .
RUN npm run build

# ---- the program ----
FROM python:3.11-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
COPY --from=pages /pages/dist /app/pages

# Records, the key that locks them, and backups each live in their own place (see docker-compose.yml).
ENV DATA_DIR=/data \
    KEY_DIR=/keys \
    BACKUP_DIR=/backups \
    STATIC_DIR=/app/pages \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
EXPOSE 8008
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8008/api/health', timeout=4)"
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8008"]
