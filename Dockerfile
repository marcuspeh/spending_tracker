FROM python:3.12-slim

# Set timezone
ENV TZ=Asia/Singapore

# Flush stdout/stderr immediately so Docker logs surface errors as they
# happen instead of buffering them until the process exits.
ENV PYTHONUNBUFFERED=1

# Install uv
RUN pip install uv

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
