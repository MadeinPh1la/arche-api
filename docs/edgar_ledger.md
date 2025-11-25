# EDGAR Bloomberg-Class Ledger

## Status Legend
- ✅ Complete
- 🟡 Partial / Foundation built, needs expansion
- 🔴 Not implemented yet

---

# Phase Completion Overview

| Phase | Description | Status |
|-------|-------------|--------|
| E1 | Domain models, enums, DTOs |  ✅ |
| E2 | EDGAR client + ingestion gateway |  ✅ |
| E3 | Filing ingestion use cases |  ✅ |
| E4 | Statement version ingestion |  ✅ |
| E5 | HTTP surface + presenters + full router |  ✅ |
| E6-F | Normalized Statement Payload Engine | 🔴 Newly added |
| E6 | Modeling endpoints (fundamentals, facts, restatements) | 🔴 Pending E6-F |
| E7 | Derived metrics (growth, margins, leverage, TTM) | 🔴 |
| E8 | Data quality, anomaly detection, reconciliation | 🔴 |
| E9 | MCP modeling interface | 🔴 |
| E10 | Advanced accounting intelligence (fiscal calendar inference, stitching, special items) | 🔴 |

---

# Capability Matrix

## 1. Domain & Contracts
| Capability | Status | Notes |
|-----------|--------|-------|
| Filing + Statement DTOs | ✅ | Solid foundation |
| Domain exceptions for EDGAR | ✅ | Stable |
| Statement version entity | 🟡 | Metadata only; payload incomplete |
| Normalized long-form schema | 🔴 | Added for E6-F |

---

## 2. Ingestion & Mapping
| Capability | Status | Notes |
|-----------|--------|-------|
| Filing ingestion | ✅ | Production-ready |
| Statement version ingestion | 🟡 | Metadata only |
| XBRL → canonical mapping | 🔴 | Required for normalized payloads |
| Extension tag support | 🔴 | Required for Bloomberg-class |

---

## 3. Persistence
| Capability | Status | Notes |
|-----------|--------|-------|
| Filing repository | ✅ | Fully tested |
| Statement version repository | 🟡 | Needs payload storage |
| Normalized payload storage | 🔴 | Part of E6-F |

---

## 4. HTTP Surface
| Capability | Status | Notes |
|-----------|--------|-------|
| Filings API | ✅ | Complete |
| Statement versions API | 🟡 | normalized_payload = null |
| Combined financials API | 🔴 | Part of E6 |
| Time-series API | 🔴 | Part of E6 |
| Facts API | 🔴 | Part of E6 |

---

## 5. Modeling Layer
| Capability | Status | Notes |
|-----------|--------|-------|
| Normalized statements | 🔴 | E6-F |
| Fundamental metrics | 🔴 | E7 |
| Multi-period financials | 🔴 | E6 |
| Restatement deltas | 🔴 | E6 |
| TTM, QoQ, YoY | 🔴 | E7 |

---

## 6. Data Quality (DQ)
| Capability | Status | Notes |
|-----------|--------|-------|
| Basic schema validation | 🟡 | Exists but shallow |
| Financial integrity checks | 🔴 | E8 |
| Reconciliation vs external sources | 🔴 | E8 |
| Restatement lineage diffs | 🔴 | E6 |

---

## 7. Observability & SLOs
| Capability | Status | Notes |
|-----------|--------|-------|
| Structured logging | ✅ | Complete |
| EDGAR metrics | 🟡 | Basic counters only |
| SLOs (latency, freshness, DQ) | 🔴 | E8/E10 |

---

## 8. MCP Modeling Interface
| Capability | Status | Notes |
|-----------|--------|-------|
| MCP metadata | 🟡 | Exists |
| MCP modeling capabilities | 🔴 | Requires E6-F, E6, E7 |

