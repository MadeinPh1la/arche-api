# Arche Architecture Overview

**Clean Architecture • Deterministic Data Platform • World-Class Reliability**

This document describes the **runtime, structural, and dependency architecture** of Arche.
It complements `ENGINEERING_GUIDE.md` and is enforced by executable tests in:

```
tests/architecture/
```

The architecture follows a strict, test-enforced layering model:

```
domain  ←  application  ←  adapters  ←  infrastructure
```

This document explains:

* Why these layers exist
* What belongs in each layer
* What is forbidden
* How data flows through the system
* How the Unit of Work (UoW) coordinates transactional boundaries
* How repository resolution works
* How entrypoints like HTTP routers and MCP capabilities fit in
* How EDGAR and Marketstack ingestion pipelines move through the architecture

This is the contract that protects Arche from entropy, accidental tight coupling, and long-term maintainability failures.

---

# **1. Core Principles**

Arche is architected as a **deterministic financial modeling platform**.
Every layer exists to uphold:

### **1.1 Isolation**

* Domain has zero dependencies.
* Application orchestrates without touching infrastructure.
* Adapters implement interfaces without leaking implementation details.
* Infrastructure is completely replaceable.

### **1.2 Determinism**

* Same inputs produce the same outputs.
* Ingestion is idempotent.
* Normalization is versioned.
* Repositories preserve historical versions, never overwriting.

### **1.3 Replaceability**

You can replace:

* SQLAlchemy with another ORM
* postgres with another DB
* Marketstack with another provider
* EDGAR clients with alternative providers
* HTTP routers with MCP or GRPC

**without rewriting the domain or application.**

### **1.4 Observability**

All critical path flows must emit:

* metrics
* structured logs
* traces

This is implemented in the adapters and infrastructure layers, never domain.

---

# **2. Layer Model**

The architecture follows a strict dependency direction:

```
domain  ←  application  ←  adapters  ←  infrastructure
```

Each arrow indicates “depends on”.

No layer may depend on a layer above it.

---

# **3. Domain Layer**

**Location:** `src/arche_api/domain/`

The domain layer contains **pure, dependency-free logic**:

* Entities
* Value objects
* Enumerations
* Domain exceptions
* Domain services
* Protocol-based interfaces (repositories and gateways)

Domain code MUST:

* Contain no I/O
* Contain no SQLAlchemy imports
* Contain no FastAPI imports
* Depend only on the standard library
* Use only domain types and domain exceptions

### **Why?**

Domain is the **core of Arche**.
It must remain engine-agnostic and provider-agnostic.

### **Tests enforcing this**

* `test_domain_isolation.py`
* `test_import_graph.py`

---

# **4. Application Layer**

**Location:** `src/arche_api/application/`

The application layer expresses **use cases**, not implementation details.

Contains:

* Use cases (EDGAR ingestion, normalization, fundamentals time series, etc.)
* DTOs
* Application-level exceptions
* Unit of Work protocol (`UnitOfWork`)
* Application-level helpers (no infrastructure)

Application code may:

* Use domain entities
* Use domain interfaces
* Use `UnitOfWork` abstraction to resolve repositories
* Orchestrate repository operations
* Validate inputs
* Log

It may **never**:

* Import concrete repositories
* Import SQLAlchemy session types
* Import HTTP clients
* Import FastAPI
* Reach into infrastructure

Repository resolution must occur via:

```python
module = import_module("arche_api.adapters.repositories.edgar_statements_repository")
repo_cls = module.EdgarStatementsRepository
statements_repo = tx.get_repository(repo_cls)
```

### **Tests enforcing this**

* `test_application_layer.py`
* `test_uow_boundaries.py`
* `test_import_graph.py`

---

# **5. Adapters Layer**

**Location:** `src/arche_api/adapters/`

Adapters implement the **edges of the system**.

Subfolders:

* `repositories/` — SQLAlchemy repository implementations
* `gateways/` — HTTP / API clients
* `presenters/` — shape domain data for HTTP/MCP
* `routers/` — FastAPI routing surfaces
* `controllers/` — HTTP controllers
* `schemas/` — Pydantic schemas for HTTP
* `uow/` — Concrete UnitOfWork implementations

Adapters may:

* Import infrastructure (DB, clients, metrics, tracing)
* Convert ORM rows → domain entities
* Convert domain entities → API envelopes
* Define FastAPI routes
* Use Pydantic models
* Use SQLAlchemy models

Adapters may NOT:

* Directly instantiate use cases that bypass UoW
* Depend on application internals except for DTOs
* Depend on other adapters unless explicitly allowed (e.g., presenter + router)

### Repo responsibilities

Repositories must:

* Provide deterministic queries
* Never mutate or overwrite historical statement versions
* Convert failures into domain exceptions
* Emit perf metrics & error metrics
* Preserve version ordering per domain rules

### **Tests enforcing this**

* `test_adapters_dependencies.py`
* `test_router_conventions.py`
* `test_import_graph.py`

---

# **6. Infrastructure Layer**

**Location:** `src/arche_api/infrastructure/`

This layer implements raw capabilities:

* Database models
* Database session provider
* HTTP clients
* Retry + circuit breaker policies
* Logging
* Metrics
* Tracing
* Middlewares
* Caching
* Background task infrastructure

Infrastructure **must not**:

* Import `application`
* Import routers
* Import presenters
* Reference domain entities directly

### **Tests enforcing this**

* `test_infrastructure_isolation.py`
* `test_import_graph.py`

---

# **7. Unit of Work (UoW)**

### **Purpose**

UoW is the **transaction boundary** of the application layer.

It coordinates:

* The lifespan of DB sessions
* Repository instantiation
* Commit / rollback
* Atomicity
* Retry behavior if implemented
* Transaction logging & metrics

### **Contract**

Application use cases must access repositories via:

```python
repo = tx.get_repository(RepoCls)
```

Concrete UoW implementations live in adapters:

```
adapters/uow/sqlalchemy_uow.py
```

These implementations:

* Hold a SQLAlchemy session
* Instantiate repositories
* Clean up on exit
* Translate DB errors to domain exceptions

### **Tests enforcing this**

* `test_uow_boundaries.py`

---

# **8. Repository Resolution Pattern**

### **Correct**

```python
module = import_module("arche_api.adapters.repositories.edgar_statements_repository")
repo_cls = module.EdgarStatementsRepository
repo = tx.get_repository(repo_cls)
```

### **Forbidden**

Application layer:

```python
from arche_api.adapters.repositories.edgar_statements_repository import EdgarStatementsRepository  # ❌
repo = EdgarStatementsRepository(session)  # ❌
```

Tests enforce this exactly.

---

# **9. Data Flow: EDGAR Example (End-to-End)**

```
HTTP Router (adapters)
    ↓  builds request DTO
Use Case (application)
    ↓  resolves repos via UoW
Repositories (adapters)
    ↓  query SQLAlchemy models
DB (infrastructure)
```

For ingestion:

1. **Gateway** (adapters) fetches EDGAR JSON
2. **Use case** (application) orchestrates logic
3. **Repositories** (adapters) upsert filings & statement versions
4. **Domain** entities returned upward
5. Presenters shape the response
6. Routers return versioned HTTP envelopes

Every step is test-enforced.

---

# **10. Import Graph & Clean Boundaries**

Architecture tests statically scan the import graph:

* If `domain/` imports anything outside domain → FAIL
* If `application/` imports adapters/infrastructure → FAIL
* If `adapters/` import application internals → FAIL
* If infrastructure leaks upward → FAIL
* If routers lack versioned prefixes → FAIL
* If repositories are constructed outside UoW → FAIL

This ensures Arche remains scalable under continuous expansion.

---

# **11. Versioning Rules for HTTP Routers**

All HTTP routers must:

* Use versioned prefixes (`/v1/…`)
* Register in `openapi_registry`
* Shape outputs via envelopes
* Avoid business logic

Adapters tests validate this.

---

# **12. EDGAR Normalized Payload Engine**

Normalized payloads must:

* Store canonical metrics as strings
* Preserve precision (Decimal)
* Use deterministic schema versions
* Remain backward-compatible for replaying older payloads
* Avoid leaking ORM or DB assumptions into domain

Repositories map these payloads faithfully in both directions.

---

# **13. Market Data Layer**

* Marketstack client is infrastructure
* MarketDataGateway is domain/application facing interface
* Use cases orchestrate ingestion + staging
* All normalization & upsert behavior is driven via repositories inside UoW

---

# **14. Testing Philosophy**

Unit tests reconstruct deterministic scenarios using:

* FakeUnitOfWork
* Fake repositories
* Fake gateways

The architecture ensures tests never depend on infrastructure.

---

# **15. Why This Architecture Matters**

This architecture is intentionally strict because Arche targets **financial modeling parity with professional platforms**:

* Deterministic versioning
* Predictable ingestion
* Strict reproducibility
* Clean audit trails
* Replaceable infrastructure
* Zero hidden side effects
* Scalability under high load and large datasets

You can scale teams, features, gateways, or persistence engines without re-architecting.

---

# **16. Cross-Links**

This document works in tandem with:

* **ENGINEERING_GUIDE.md**
  *Authoritative rules + “may/may not” constraints enforced by tests*

* **API_STANDARDS.md**
  *HTTP-level behavior, envelope contracts, pagination, error shape*

* **DEFINITION_OF_DONE.md**
  *Quality bars, validation, tests, coverage thresholds*

* **TESTING_GUIDE.md**
  *Patterns for writing domain, application, and adapter tests*

* **tests/architecture/**
  *Executable enforcement of all architectural rules*

---

# **17. Final Notes**

This architecture is not optional.
It is the backbone of Arche's long-term maintainability and professional-grade expansion.
