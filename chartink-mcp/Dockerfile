# Render/Railway: use this Dockerfile (Environment = Docker). Chromium is installed
# below for POST /refresh-session; startup does not run Playwright by default.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Required when using Playwright for session refresh (not needed at app startup).
RUN playwright install --with-deps chromium

COPY . .

RUN mkdir -p /app/data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
