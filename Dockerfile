# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — Build / dependency resolver
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install system build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        git \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements first (layer-caching optimisation)
COPY requirements.txt .

# Install into an isolated prefix so we can copy cleanly to the runtime stage
RUN pip install --upgrade pip \
 && pip install --prefix=/install --no-cache-dir -r requirements.txt


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — Slim runtime image
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Labels
LABEL maintainer="your-team@example.com"
LABEL description="AWS Cost Intelligence Assistant — FastAPI backend"
LABEL version="1.0.0"

# Non-root user for security
RUN groupadd --system appgroup && useradd --system --gid appgroup appuser

WORKDIR /app

# Copy installed packages from the builder stage
COPY --from=builder /install /usr/local

# Copy application source
COPY app/ ./app/

# Create runtime directories and set permissions
RUN mkdir -p logs \
 && chown -R appuser:appgroup /app

# Switch to non-root user
USER appuser

# Environment defaults (overridden at runtime via --env-file or -e flags)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_NAME="AWS Cost Intelligence Assistant" \
    APP_VERSION="1.0.0" \
    LOG_LEVEL=INFO \
    DEBUG=false \
    LOG_DIR=/app/logs

# Expose the FastAPI port
EXPOSE 8000

# Health check — hits the liveness probe every 30 s
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Production server: 4 Uvicorn workers, structured access logs disabled
# (RequestLoggingMiddleware handles per-request logging)
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "4", \
     "--loop", "uvloop", \
     "--http", "httptools", \
     "--no-access-log"]
