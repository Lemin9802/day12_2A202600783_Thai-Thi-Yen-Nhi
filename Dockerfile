# ── Stage 1: Build React frontend ─────────────────────────────────────────────
FROM node:20-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci --silent
COPY frontend/ ./
# Empty API_BASE = same-origin, no localhost hardcode
ENV VITE_API_BASE=""
RUN npm run build

# ── Stage 2: Install Python deps ─────────────────────────────────────────────
ARG PYTHON_IMAGE=python:3.12-slim-bookworm
FROM ${PYTHON_IMAGE} AS py-builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ── Stage 3: Runtime ─────────────────────────────────────────────────────────
FROM ${PYTHON_IMAGE} AS runtime
RUN groupadd -r appuser && useradd -r -g appuser appuser
WORKDIR /app

COPY --from=py-builder /root/.local /home/appuser/.local
COPY backend ./backend
COPY utils ./utils
COPY data ./data
COPY scripts ./scripts
COPY requirements.txt .
COPY --from=frontend-builder /frontend/dist ./frontend/dist

RUN chown -R appuser:appuser /app
USER appuser

ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONPATH=/app
ENV HOST=0.0.0.0
ENV PORT=8000
ENV APP_NAME="MaiThuyLaw AI"
ENV APP_VERSION="1.0.0"

RUN python scripts/build_dense_index.py

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request, os; urllib.request.urlopen('http://localhost:' + os.getenv('PORT','8000') + '/ready')" || exit 1

CMD ["sh", "-c", "python -m uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

