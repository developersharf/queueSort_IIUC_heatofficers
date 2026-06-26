# syntax=docker/dockerfile:1
# ----------------------------------------------------------------------------
# QueueStorm Investigator — production image
#
# Works on:
#   - Railway  (auto-detected, $PORT set, $RAILWAY_PUBLIC_DOMAIN set)
#   - Docker / docker compose
#   - Any host that can run a container and set $PORT
#
# Hackathon constraints honored:
#   - Port bound to 0.0.0.0:$PORT                 (rule: "Must bind to 0.0.0.0")
#   - /health responds within ~5 s of boot       (rule: "/health within 60 s")
#   - No secrets baked into the image            (rule: "Secrets via env only")
#   - Image < 500 MB                             (rule: recommended image size)
# ----------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings \
    PORT=8000

# Minimal system deps: curl for healthcheck, ca-certificates for HTTPS.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Create a non-root user and own /app. Required for Railway's gVisor sandbox.
RUN groupadd --system --gid 1000 app \
 && useradd  --system --uid 1000 --gid app --home /app --shell /usr/sbin/nologin app

WORKDIR /app

# Install Python deps first for better layer caching.
COPY --chown=root:root requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy the rest of the project.
COPY --chown=app:app . /app

# Directories the app writes to at runtime:
#   /app/data  — SQLite database (set via DJANGO_SQLITE_PATH)
#   /app/staticfiles — collected static files (Django admin CSS, etc.)
RUN mkdir -p /app/data /app/staticfiles \
 && chown -R app:app /app/data /app/staticfiles

USER app

EXPOSE 8000

# Built-in healthcheck — Docker / Railway / docker compose honor this.
# The rule says /health must answer within 60 s; we probe every 30 s after a
# 15 s grace period.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# Production CMD:
#   1. Collect static files for whitenoise
#   2. Run migrations
#   3. Boot gunicorn on 0.0.0.0:$PORT with 3 workers
CMD ["sh", "-c", "python manage.py collectstatic --noinput && python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:${PORT} --workers 3 --timeout 60 --access-logfile - --error-logfile -"]