FROM python:3.12-slim

# Set timezone
ENV TZ=Asia/Singapore

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
    CMD python -m app.cli healthcheck

# Run the application
CMD ["python", "-m", "app.main"]
