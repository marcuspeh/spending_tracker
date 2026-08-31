FROM python:3.12-slim

# Set timezone
ENV TZ=Asia/Singapore

# Flush stdout/stderr immediately so Docker logs surface errors as they
# happen instead of buffering them until the process exits.
ENV PYTHONUNBUFFERED=1

# Install uv and git (uv needs git to fetch the config_store_sdk
# dependency sourced from a Git repo; the python:3.12-slim base image
# doesn't ship with it).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install uv

WORKDIR /app

# Copy dependency files first for better caching
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-install-project

# Copy application source
COPY app/ ./app/

# Healthcheck probes the in-process HTTP endpoint
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD uv run python -m app.cli healthcheck

# Run the application via uv so it picks up the .venv created above
CMD ["uv", "run", "python", "-m", "app.main"]
