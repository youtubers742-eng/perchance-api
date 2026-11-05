# Perchance Image API — generic Docker image (host-agnostic).
# Works on any host that runs containers: Render (Docker path), Railway,
# Fly.io, Hugging Face Spaces (Docker), a VPS, etc. The primary deploy is
# Render's native Python environment via render.yaml — this Dockerfile is
# the fallback for Docker-based hosts.
#
# The Playwright Chromium install makes this image large (~700MB) — it is
# needed ONLY for the automatic userKey refresh (Cloudflare Turnstile).
# If your host cannot run Chromium, set PERCHANCE_USER_KEY instead and
# the server runs without ever launching a browser.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# curl + CA certs for healthchecks / debugging.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium --with-deps

COPY . .

# Render / Railway / Fly set $PORT; default to 8000 locally.
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]
