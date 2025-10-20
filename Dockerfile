# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y build-essential libpq-dev curl && rm -rf /var/lib/apt/lists/*

# Copy dependencies
COPY pyproject.toml poetry.lock* requirements*.txt ./

# Install dependencies
RUN pip install --upgrade pip && pip install -e ".[dev]" --no-cache-dir

# Copy source
COPY src ./src

# Run
CMD ["uvicorn", "stacklion_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
