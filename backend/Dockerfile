# =============================================================
# Archer - Dockerfile
# Build context: repo root
#   docker build -f backend/Dockerfile -t archer-backend:local .
#
# One image serves both halves: FastAPI serves the API and the built React
# application from the same origin. That keeps the session cookie working
# without CORS, and means one thing to deploy rather than two.
# =============================================================

# -------------------------------------------------------------
# Stage 1: build the React frontend.
# Node is needed to build it and is not needed to run it, so it stays in this
# stage and never reaches the runtime image.
# -------------------------------------------------------------
FROM node:20-slim AS frontend-build

WORKDIR /build

# Manifests first so the dependency install layer is cached independently of
# application code.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# -------------------------------------------------------------
# Stage 2: the runtime image.
# -------------------------------------------------------------

# 1. Base image: official slim Python 3.12 (minimal CVE surface)
FROM python:3.12-slim

# 2. Python runtime environment variables
#    PYTHONDONTWRITEBYTECODE: prevents .pyc files being written inside the container
#    PYTHONUNBUFFERED: ensures stdout/stderr are flushed immediately (visible in logs)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 3. Apply latest OS security patches
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 4. Create a non-root system user and group for runtime isolation
RUN addgroup --system appgroup \
    && adduser --system --ingroup appgroup appuser

# 5. Set working directory
WORKDIR /app

# 6. Install Python dependencies
#    Copied first to leverage Docker layer cache - only re-runs when requirements change
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 7. Hand /app to the non-root user and drop privileges before anything else
#    is written into it.
#
#    Ordering matters more than it looks. A `chown -R` after copying would
#    rewrite every file into a fresh layer, duplicating the whole 47MB dataset
#    and adding it to the image twice. Chowning the empty directory costs
#    nothing, and everything after this is written as appuser already.
RUN chown appuser:appgroup /app
USER appuser

# 8. Build the synthetic dataset into the image.
#    The dataset is generated from a seeded script rather than shipped as a
#    binary: the repository stays small, anyone can reproduce the data
#    exactly, and the evaluation suite can rely on fixed rows.
#
#    Generating at build time also means the running container makes no network
#    call, needs no object-storage credentials, and does not pay for a 47MB
#    download on every cold start - which matters because the deployment
#    scales to zero between visitors.
#
#    This sits BEFORE the application source deliberately. The dataset layer
#    depends only on the generator, so it is cached and reused across deploys
#    where only application code changed. Putting it after the source would
#    push a fresh 47MB layer on every single deploy.
COPY --chown=appuser:appgroup scripts/generate_dataset.py ./scripts/
RUN python scripts/generate_dataset.py --output /app/sales.db \
    && rm -rf scripts

# 9. Copy the built React application from the build stage.
#    archer/core/paths.py looks for /app/frontend in the container.
COPY --from=frontend-build --chown=appuser:appgroup /build/dist ./frontend

# 10. Copy the prompts. They are loaded from disk at runtime, so the image is
#     not usable without them - archer/core/paths.py looks for /app/prompts.
COPY --chown=appuser:appgroup prompts/ ./prompts/

# 11. Copy application source files. Last, because they change most often and
#     are small, so a code-only change rebuilds only these layers.
COPY --chown=appuser:appgroup backend/main.py .
COPY --chown=appuser:appgroup backend/__init__.py .
COPY --chown=appuser:appgroup backend/archer/ ./archer/
COPY --chown=appuser:appgroup backend/templates/ ./templates/
COPY --chown=appuser:appgroup backend/static/ ./static/

# 12. Expose the default port
EXPOSE 8080

# 13. Start the server
#     Shell form is used to allow ${PORT:-8080} expansion (IBM Code Engine injects PORT)
#     exec replaces the shell process so uvicorn receives OS signals directly
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
