# Stacklion API

### The financial data layer for modern finance teams

[![Build Status](https://img.shields.io/github/actions/workflow/status/MadeinPh1la/stacklion-api/ci.yml?branch=main\&label=build)](https://github.com/MadeinPh1la/stacklion-api/actions)
[![Pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit\&logoColor=white)](https://pre-commit.com/)
[![License](https://img.shields.io/badge/license-BSL%201.1-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Code Style: Black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Type Checking: MyPy](https://img.shields.io/badge/type%20checking-mypy-2E78C5.svg)](https://mypy-lang.org/)
[![Lint: Ruff](https://img.shields.io/badge/lint-ruff-green.svg)](https://github.com/astral-sh/ruff)

---

## Overview

**Stacklion API** unifies corporate fundamentals, market data, portfolio analytics, and risk intelligence into one high-integrity data platform.
It is designed for developers, quants, and fintech teams who demand verified, versioned, and strongly typed financial data—served through a single, governed API.

---

## Core Concepts

| Domain           | Description                                                        |
| ---------------- | ------------------------------------------------------------------ |
| Fundamentals     | EDGAR-sourced balance sheets, income statements, and cash flows.   |
| Market Data      | Real-time and end-of-day pricing via MarketStack V2 adapters.      |
| Valuation & Risk | DCF, CAPM, Monte Carlo, Value-at-Risk, and stress-testing engines. |
| Portfolios       | Multi-asset composition, optimization, and rebalancing.            |
| Governance       | Full audit trails, versioning, and model-lineage metadata.         |

---

## Architecture

Stacklion follows **Clean Architecture** and **YAGNT** principles:

```
src/
├── domain/           # Pure entities, value objects, and exceptions
├── application/      # Use cases, services, and DTOs
├── adapters/         # Routers, controllers, presenters, repositories
├── infrastructure/   # Database, caching, logging, middleware
├── config/           # Environment & settings
└── main.py           # Composition root (FastAPI entrypoint)
```

### Technology Stack

* FastAPI + Uvicorn – asynchronous web layer
* SQLAlchemy 2 (Async) – ORM and persistence
* PostgreSQL + Redis – database and caching
* Celery + Flower – background scheduling and ingestion
* Pydantic v2 – typed DTOs and schema contracts
* Docker + Compose – local and cloud deployments
* Ruff · Black · MyPy · Pre-commit – code quality gates

---

## Setup

```bash
# 1. Clone your fork
git clone git@github.com:MadeinPh1la/stacklion-api.git
cd stacklion-api

# 2. Create a virtual environment
python3 -m venv .venv && source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt -r requirements-dev.txt

# 4. Configure environment
cp .env.example .env    # edit values for database, Redis, and API keys

# 5. Run locally
uvicorn src.main:app --reload --port 8080
```

Visit [http://127.0.0.1:8080/docs](http://127.0.0.1:8080/docs) for live OpenAPI documentation.

---

## Quality and Tooling

| Tool       | Purpose                                       |
| ---------- | --------------------------------------------- |
| Black      | Auto-formatting (PEP 8 + Stacklion standards) |
| Ruff       | Static analysis, import sorting, and linting  |
| MyPy       | Strict type checking                          |
| Pre-commit | Enforces all of the above on every commit     |

Run manually:

```bash
ruff check .
black .
mypy .
```

---

## Development Principles

* **Clean Architecture strictly enforced** – the domain layer never imports FastAPI or SQLAlchemy.
* **Google-style docstrings and OpenAPI examples** across all layers.
* **No placeholders or speculative abstractions.**
* **Asynchronous first** – all repositories and services use async execution.
* **Audit and versioning required** for all financial statements.

---

## Deployment (Docker)

```bash
docker compose up --build
```

| Service | Port | Description         |
| ------- | ---- | ------------------- |
| api     | 8080 | FastAPI application |
| db      | 5432 | PostgreSQL          |
| redis   | 6379 | Redis cache         |
| worker  | —    | Celery worker       |
| flower  | 5555 | Task monitoring UI  |

---

## Contributing

Contributions are welcome under Stacklion’s open-core model.
Please review:

* [`CONTRIBUTING.md`](CONTRIBUTING.md) – workflow and PR requirements
* [`ENGINEERING_GUIDE.md`](ENGINEERING_GUIDE.md) – coding standards
* [`DEFINITION_OF_DONE.md`](DEFINITION_OF_DONE.md) – acceptance criteria
* [`API_STANDARDS.md`](API_STANDARDS.md) – schema and naming conventions

Typical branch workflow:

```bash
git checkout -b feature/<scope>/<summary>
pre-commit run --all-files
git commit -m "feat(<scope>): <description>"
git push origin feature/<scope>/<summary>
```

---

## License and Usage

### Core Server

Licensed under the **Business Source License 1.1 (BSL 1.1)**
© 2025 Northern Lion Labs LLC
Production or commercial use requires a commercial agreement.
After **2028-10-15**, it automatically converts to the **Apache 2.0 License**.

### SDKs and Tooling

Licensed separately under the **MIT License** to maximize developer adoption.

See [`LICENSE`](LICENSE), [`COMMERCIAL.md`](COMMERCIAL.md), and [`NOTICE`](NOTICE).

---

## Contact

**Northern Lion Labs LLC**
Website: [https://stacklion.io](https://stacklion.io)
Email: [support@northernlion.io](mailto:support@northernlion.io) · [licensing@northernlionlabs.com](mailto:licensing@northernlionlabs.com)
GitHub: [@MadeinPh1la](https://github.com/MadeinPh1la) · [@NorthernLionLabs](https://github.com/NorthernLionLabs)

---

**Stacklion API — Built for accuracy, auditability, and performance in modern finance.**

---

Would you like me to also generate the short `README.md` variant for the SDK repos (`stacklion-sdk-python` and `stacklion-sdk-js`) so all public repos have consistent branding and structure?
