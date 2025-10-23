# syntax=docker/dockerfile:1
FROM python:3.12-slim

# --- Base env ---
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# --- OS deps (build & libpq for asyncpg) ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
 && rm -rf /var/lib/apt/lists/*

# --- Copy project metadata first (better layer caching) ---
COPY pyproject.toml README.md ./

# --- Copy source ---
# For editable install, need the actual source present
COPY src ./src

# --- Install (editable, includes your dev extras if you want) ---
# If defined "otel" extra in pyproject, use .[dev,otel]; otherwise .[dev]
RUN pip install --upgrade pip \
 && pip install --no-cache-dir -e ".[dev,otel]"

# --- Default dev command (factory to ensure lifespan runs) ---
CMD ["uvicorn", "stacklion_api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--reload"]
