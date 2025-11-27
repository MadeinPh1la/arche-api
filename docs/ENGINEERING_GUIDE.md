# Engineering Quality Standard (EQS)

**Scope:** This is the single source of truth for **typing, logging, SQLAlchemy, dependency injection (DI), testing, observability, security, performance, deployment hygiene, and Clean Architecture practice** across Stacklion.

- The public HTTP contract (routes, envelopes, errors, pagination, headers, versioning, idempotency) is defined in **`API_STANDARDS.md`** and is authoritative for anything “on the wire.”
- If there’s any conflict: **`API_STANDARDS.md` wins for HTTP contracts; EQS wins for engineering practice.**

---

## 0) Architectural Canon (non-negotiable)

### 0.1 Layers

We treat the codebase as **three logical layers**:

- **Domain**
  - What lives here:
    - Entities, value objects, domain services, domain exceptions, domain interfaces.
  - Rules:
    - **No** framework/HTTP/ORM imports.
    - No direct knowledge of databases, HTTP, Redis, EDGAR, Marketstack, MCP, etc.
    - Logging is minimal and **never** depends on infra loggers (use stdlib logging only if needed).

- **Application**
  - What lives here:
    - Use cases / services / orchestrations.
    - DTOs (request/response shapes for use cases).
    - Unit of Work abstractions.
    - Ports/interfaces that express what the outer layer must implement.
  - Rules:
    - **No** HTTP envelopes.
    - **No** ORM models.
    - **No** direct imports from `adapters.*` or `infrastructure.*`.
    - May raise domain exceptions.

- **Outer layer (Adapters + Infrastructure)**
  - Treated as a **single outer ring** for dependency rules.
  - What lives here:
    - Adapters:
      - Repositories, presenters, routers/controllers, HTTP schemas, DI/dependencies, MCP binding.
    - Infrastructure:
      - DB models + sessions, Redis clients, HTTP clients (EDGAR/Marketstack/etc.), logging, metrics, tracing, middleware, resilience (retry/circuit-breaker), settings.
  - Rules:
    - All vendor/transport concerns live here.
    - All framework integration (FastAPI, SQLAlchemy, httpx, Redis) lives here.
    - Cross-imports between `adapters.*` and `infrastructure.*` are allowed and expected.

### 0.2 Allowed dependency directions

We enforce **directional dependencies** between the logical layers:

- **Domain**
  - May depend only on `stacklion_api.domain.*`.

- **Application**
  - May depend on:
    - `stacklion_api.application.*`
    - `stacklion_api.domain.*`
  - Must **not** depend on:
    - `stacklion_api.adapters.*`
    - `stacklion_api.infrastructure.*`

- **Outer layer (Adapters + Infrastructure)**
  - May depend on:
    - `stacklion_api.adapters.*`
    - `stacklion_api.infrastructure.*`
    - `stacklion_api.application.*`
    - `stacklion_api.domain.*`
  - This layer is intentionally permissive so operational wiring is not artificially constrained.

Package → layer mapping:

- `stacklion_api.domain.*` → **domain**
- `stacklion_api.application.*` → **application**
- `stacklion_api.adapters.*` → **outer**
- `stacklion_api.infrastructure.*` → **outer**

### 0.3 Architecture tests

`tests/arch/test_layering.py` encodes the rules above by analyzing the import graph:

- It maps modules into the three layers above.
- It asserts that:
  - `domain` only imports `domain`.
  - `application` only imports `application` + `domain`.
  - `outer` (adapters + infra) can import `outer` + `application` + `domain`.

If you introduce new top-level packages or change structure in a layer-sensitive way, you **must** update the architecture test so it continues to reflect the intended rules.

### 0.4 Contracts & DTOs

- Application returns **DTOs only**.
- **Presenters** are the **only** layer that shape **HTTP envelopes**.
- Transport-specific schemas live under `src/stacklion_api/adapters/schemas/http/`.
- Application DTOs live under `src/stacklion_api/application/schemas/dto/`.

### 0.5 Glossary (build policy)

- **YAGNT — “You ARE Gonna Need This.”**  
  We proactively implement essentials that are *certain* for safe, operable production:
  - Boundary validation
  - Error translation
  - Audit/versioning
  - Logging/tracing
  - Metrics
  - Idempotency
  - Deterministic pagination/order
  - Migrations
- **YAGNI — “You Aren’t Gonna Need It.”**  
  We do **not** implement speculative features, premature abstractions, or optional knobs until:
  - There is a concrete use case, and
  - We can show it adds value.

**Policy:** We are **YAGNT for operability and correctness**, **YAGNI for speculative features**.

---

## 1) Documentation (mandatory)

- Module-level header for all public modules (use `MODULE_HEADER_TEMPLATE.md`).
- **Google-style docstrings** for every public class/method/function (see `GOOGLE_DOCSTRING_TEMPLATE.md`).
- Private helpers may omit docstrings only when trivial and non-API-facing.
- Every **public** schema (DTO/HTTP) includes:
  - Field descriptions.
  - `json_schema_extra` examples.

---

## 2) Error Handling (boundary-first)

- Repositories/infra translate third-party/driver errors → **domain exceptions**.
- Controllers/routers translate domain exceptions → **HTTP** per **`API_STANDARDS.md`**.
- **Never swallow** exceptions. Use `logger.exception(...)` on error paths.
- Transactional code must **rollback** on any exception (see §11 SQLAlchemy).
- Error messages are **safe** (no secrets/PII). Presenters include `trace_id` in error envelopes.

---

## 3) Logging (structured, minimal, useful)

- Use the shared project logger; **no `print()`**.
- **Boot logs** (INFO/DEBUG):
  - DB engine/sessionmaker creation.
  - Redis client init.
  - DI wiring.
  - Settings checksum (no secrets).
- **Business lifecycle** (INFO):
  - `entity_created`, `entity_updated`, `entity_deleted`.
  - Batch/job milestones.
- **User/validation errors**: WARNING.  
  **Unexpected failures**: ERROR/EXCEPTION.
- **No secrets/PII** in logs. Redact tokens, API keys, passwords, SSNs, etc.

---

## 4) Validation

- **Boundary validation** using FastAPI/Pydantic (HTTP layer).
- **Domain invariants** enforced in Application/Domain via domain exceptions.
- Avoid duplicate checks unless invariants require it (e.g., optimistic concurrency, money precision).

---

## 5) API/OpenAPI (pointer)

- All HTTP rules—envelopes, pagination, errors, headers, idempotency—are governed by **`API_STANDARDS.md` (authoritative)**.
- Presenters **must** use the Contract Registry envelopes:
  - `SuccessEnvelope`
  - `PaginatedEnvelope`
  - `ErrorEnvelope`

---

## 6) Code Standards

- **Typing:**
  - Full typing throughout.
  - Avoid `Any`. If unavoidable, justify inline and isolate.
- **Compatibility:**
  - Prefer `Optional[T]` over `T | None` where FastAPI/Pydantic parity requires it.
- **Style & Tooling:**
  - Ruff + Black + MyPy (`--strict`) gated in CI.
  - Imports rooted at `src/stacklion_api`.
  - No dead imports.
  - No TODOs/placeholders in mainline code paths.
- **Naming:**
  - Use canonical fields (`statement_date`, `page`, `page_size`, `total`, `items`) consistently across layers.
- **Architecture tests:**
  - `tests/arch/test_layering.py` **must** pass.
  - When adding new module trees that are layer-sensitive, update the test to keep it aligned with the rules in §0.

---

## 7) Observability (metrics, tracing, health)

- **Request correlation:**
  - Accept `X-Request-ID`.
  - Generate one if missing.
  - Echo in responses.
  - Inject as `trace_id` in errors.
- **Metrics:**
  - Counters/histograms for:
    - Request latency.
    - DB query time.
    - Cache hit/miss.
    - Error rates.
    - Queue latencies.
- **Tracing:**
  - Propagate trace IDs across HTTP clients and background workers.
- **Health/Readiness:**
  - `/healthz` (cheap).
  - `/readyz` (DB + Redis checks).
  - Background probe for dependencies as appropriate.

---

## 8) Security & Secrets

- **Auth:**
  - Primary scheme: `Authorization: Bearer <JWT>`.
  - API keys (if used): `X-Api-Key`.
- **Scopes/claims:**
  - Enforced at router/controller.
  - Documented on endpoints.
- **Secrets:**
  - **Never** hardcode.
  - Load via settings + env/secret manager.
  - `ConfigDict(extra='forbid')` on Settings to catch drift.
- **Input hardening:**
  - Validate lengths, enums, numeric bounds.
  - Reject unexpected fields.
- **Output hardening:**
  - Never leak internals/stack traces.
  - Redact secrets in error logs.

---

## 9) Async & DI

- **No blocking I/O** in async paths.
  - Use async DB drivers and async HTTP clients.
- Acquire DB sessions via **DI providers** (session factory), not ad-hoc constructors.
- On exception inside a transaction:
  - `await session.rollback()`
  - Re-raise as domain exception from repositories, or translate at controllers.

---

## 10) Testing & QA

- **Test pyramid:**  
  Unit > integration > e2e. Async tests use `pytest-asyncio` (or equivalent).
- **Coverage gate:**
  - Target: high coverage on application + outer layers.
  - Critical paths (auth, repositories, presenters) must maintain strong coverage and be explicitly guarded in CI.
- **OpenAPI snapshot tests:**
  - Assert spec stability and envelope shapes.
  - Prevent accidental contract drift.
- **Property-based tests** where valuable:
  - Parsing.
  - Money arithmetic.
  - Time windows.
- **DB tests:**
  - Run against ephemeral Postgres (not SQLite).
  - Alembic migrations applied.
- **Perf tests** for hot endpoints:
  - Market data lists.
  - Financial statement lists.
  - Guard SLIs/SLOs.

---

## 11) SQLAlchemy (2.0, deterministic)

- **Modeling:**
  - Use `Mapped[...]`, `mapped_column()`, typed relationships.
  - Base model includes audit mixin (`created_at/by`, `updated_at/by`).
- **Queries:**
  - In `WHERE` clauses that may yield non-boolean expressions, **explicitly cast to Boolean**:
    - `cast(expr, Boolean)`
  - Always specify deterministic **ordering**; tie-break with primary key to avoid pagination jitter.
  - Document **NULLS FIRST/LAST** behavior where relevant and keep it consistent.
- **Transactions:**
  - Use explicit `async with session.begin():` (or equivalent) for write flows.
  - On failure:
    - `logger.exception(...)`
    - `await session.rollback()`
    - Re-raise a domain exception (repository) or translate (controller).
- **Concurrency:**
  - Prefer **optimistic locking** (version column) for upserts/edits.
  - For batch ingest, use idempotency keys and conflict handling (see §14 Deployment/Runtime and API idempotency).

---

## 12) Data Integrity (money, time, precision)

- **Money/precision:**
  - No binary floats in JSON or DB.
  - Use **Decimal** in DB.
  - Return **decimal strings** on the wire.
  - Always include `currency` (enum `CurrencyCode`).
- **Timestamps:**
  - Store UTC.
  - Emit ISO-8601 with `Z`.
  - Dates as `YYYY-MM-DD`.
- **Immutability (statements):**
  - Ingested statements are immutable versions.
  - Changes create a new version with provenance (`is_restated`, `restatement_reason`, `version_source`).

---

## 13) Caching & Rate Limiting

- **Redis:**
  - Single client (singleton).
  - Exponential backoff on connect.
  - Health checks.
  - Namespace keys by service + version; include tenant/user when scoped.
- **Cache keys:**
  - Hash normalized request params.
  - Include version and permission slice where applicable.
- **TTL:**
  - Document per-endpoint TTLs.
  - Presenters set `ETag` and respect `If-None-Match` (304) when enabled.
- **Rate limiting:**
  - Global defaults; per-route overrides documented.
  - 429 responses include `Retry-After`, `X-RateLimit-*` (per API Standards).

---

## 14) Deployment & Runtime Rules

- **Config:**
  - Pydantic Settings with `ConfigDict(extra='forbid')`.
  - Per-env files: `.env`, `.env.test`.
  - No silent fallbacks.
- **CI/CD gates:**
  - Ruff, Black, MyPy `--strict`, pytest (incl. OpenAPI snapshots), Bandit (security), license checks.
  - No bypass without sign-off.
- **Idempotency:**
  - For idempotent writes (bulk ingest, sync, restore), **require** `Idempotency-Key`.
  - Return the **same** 2xx/4xx within the window.
  - Store dedupe records with TTL and status payload.
- **Retries:**
  - Outbound I/O uses bounded retries with jittered exponential backoff.
  - Define **timeouts**.
  - Implement **circuit breakers** for flaky deps.
- **Migrations:**
  - Alembic migrations are mandatory.
  - No ORM-autogen changes merged without reviewed migration scripts.
  - Zero-downtime doctrine: backward-compatible SQL first, code second.
- **YAGNT vs YAGNI enforcement:**
  - Operability gates (logs/metrics/tracing, retries/timeouts, idempotency for writes, migrations) are **mandatory**.
  - New feature flags/options/extensibility points are **deferred** until justified by a real use case.

---

## 15) Auditing, Versioning, Provenance

- **Audit mixin:**
  - `created_at`, `created_by`, `updated_at`, `updated_by` on all mutable tables.
- **Versioning:**
  - Financial statements and forecasts are **versioned**.
  - Never overwrite—new version with `is_restated`, `restatement_reason`, `version_source`.
- **Provenance:**
  - Persist external source IDs (EDGAR accession, dataset version) and timestamps for traceability.
- **Restore flows:**
  - Treated like writes.
  - Idempotent with keys.
  - Fully logged.
  - Exposed via dedicated endpoints (per API Standards).

---

## 16) Repositories — Determinism Checklist

- Explicit **ordering** for list queries; stable across identical inputs.
- Controlled **NULL** semantics and tie-breakers.
- **Boolean casts** in `WHERE` clauses as needed (`cast(..., Boolean)`).
- No business logic, no HTTP concerns, no envelope shapes.
- Return DTO-friendly structures (or ORM models mapped immediately to DTOs via mappers).

---

## 17) Presenters — Envelope Checklist

- **Only** layer allowed to construct HTTP envelopes.
- Use Contract Registry shapes:
  - `SuccessEnvelope[T]`
  - `PaginatedEnvelope[T]`
  - `ErrorEnvelope`
- Always echo `X-Request-ID`.
- Add caching headers (ETag) and rate-limit headers when applicable.
- Never mutate domain semantics; formatting only.
- Map domain exceptions → error envelopes with canonical `code` and `http_status`.

---

## 18) Routers/Controllers — Boundary Checklist

- Routers:
  - Declare routes, dependencies, and `response_model`/`responses`.
  - Contain **no business logic**.
- Controllers:
  - Orchestrate application services.
  - Translate domain exceptions → HTTP.
- Controllers never import ORM or transport-external concerns:
  - Keep to DTOs + service interfaces.
- Respect **idempotency**:
  - If endpoint opts in, require/propagate `Idempotency-Key`.

---

## 19) External Clients (EDGAR/Marketstack/etc.)

- Timeouts required.
- Bounded retries with jitter.
- Circuit breaker for repeated failures.
- Response validation + normalization at adapter boundary.
- Translate transport/HTTP errors → domain exceptions.
- Response caching (if safe) with namespaced keys and TTLs.
- Cache-stampede protection for hot paths.

---

## 20) Background Work (Celery/CLI)

- Tasks are **idempotent** and **re-entrant**:
  - Use idempotency keys and dedupe tables when altering state.
- Retries with backoff:
  - **Max attempts** and dead-letter routing configured.
- Audit logs:
  - Start, success, failure (with `trace_id` correlation).
- CLI commands mirror task semantics:
  - **Never** bypass validation or audit.

---

## 21) Performance SLIs (target class)

- P50/P95 latency budgets for hot list endpoints (e.g., market data, statements).
- DB query budgets:
  - Count + cumulative time per request.
- Cache hit ratio targets; alert if falling below threshold.
- Memory/connection pool ceilings with backpressure rather than unbounded growth.

---

## 22) Branching, Commits, Reviews

- Conventional commits:
  - `feat:`, `fix:`, `refactor:`, `perf:`, etc.
  - **Scopes** align to verticals (`income_statement`, `market_data`, `auth`, etc.).
- All PRs must include:
  - Rationale.
  - Risk.
  - Migrations.
  - Testing notes.
  - Link to API Standards if any contract changes.
- No force-push to protected branches.
- Reviews required for:
  - Migrations.
  - Contract changes.
  - Security-sensitive code.

---

## 23) Definition of Done (EQS)

A change is **not done** unless all of the below are true:

- ✅ Adheres to **YAGNT (operability/correctness)** and **YAGNI (no speculative features)**.
- ✅ Clean Architecture boundaries preserved:
  - Domain/application do not depend on adapters/infra.
  - Presenters own envelopes.
- ✅ Types complete; no stray `Any` without justification.
- ✅ DTOs and HTTP schemas documented with examples; `extra='forbid'`.
- ✅ Logs, metrics, and tracing wired; no PII/secrets; `X-Request-ID` echoed.
- ✅ Repositories: deterministic ordering, boolean casts, explicit transactions.
- ✅ Errors: domain → HTTP mapping correct; canonical error envelope used.
- ✅ Idempotency (if applicable): key validated, same response on retry, dedupe stored.
- ✅ OpenAPI snapshot tests green; unit/integration tests passing; coverage thresholds met.
- ✅ Alembic migrations reviewed and applied in CI (where relevant).
- ✅ API Standards cross-checked for any contract effect; changelog updated.
- ✅ Architecture tests (e.g., `test_layering.py`) pass and still reflect the intended rules.

---

## 24) Canonical Config Snippets (for consistency)

**Pydantic Settings**

```python
from pydantic import BaseSettings, ConfigDict

class Settings(BaseSettings):
    model_config = ConfigDict(extra="forbid")

    environment: str
    database_url: str
    redis_url: str
    jwt_issuer: str
    # Sensitive fields loaded from env/secret manager; never logged or printed.
````

**Logger usage**

```python
logger = get_logger(__name__)
logger.info(
    "market_data_ingest.start",
    extra={"trace_id": trace_id, "batch": batch_id},
)
try:
    ...
except Exception:
    logger.exception(
        "market_data_ingest.failed",
        extra={"trace_id": trace_id, "batch": batch_id},
    )
    await session.rollback()
    raise
```

**SQLAlchemy boolean cast + deterministic ordering**

```python
from sqlalchemy import Boolean, cast, select

stmt = (
    select(Model)
    .where(cast(Model.is_active == True, Boolean))  # noqa: E712
    .order_by(Model.statement_date.desc(), Model.id.asc())
)
```

---

### Final Notes

* If it’s not in **EQS** (or explicitly linked), it’s **not** a practice we rely on.
* If it’s not in **`API_STANDARDS.md`**, it’s **not** a public contract.
* Prefer **clarity, determinism, and stability** over cleverness. Consistency wins.

```
