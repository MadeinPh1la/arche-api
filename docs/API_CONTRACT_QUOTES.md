# API Contract – Quotes 

This document freezes the public HTTP contract for the **quotes vertical** as of
Contract Version **v1**. It is the authoritative reference for:

- `GET /v2/quotes`
- `GET /v2/quotes/historical`

This contract is **stable** for MCP v1. Any breaking change requires either:

- a new HTTP version (e.g. `/v3/...`), and/or
- a new contract version and MCP manifest update.

---

## 1. Overview

### 1.1 Scope

- Latest quotes (snapshots) for multiple tickers.
- Historical OHLCV bars, paginated, with optional caching via ETag.
- Read-only; no write semantics in this vertical.

### 1.2 Versioning

- Base path: `/v2/...`
- Contract version: `quotes-contract-v1`
- MCP v1 is hard-bound to this contract; MCP v2 will target future versions.

---

## 2. `GET /v2/quotes` – Latest Quotes

### 2.1 Summary

Returns latest quotes for up to 50 tickers.

- **Method**: `GET`
- **Path**: `/v2/quotes`
- **Response model**: `SuccessEnvelope[QuotesBatch]`
- **Caching**: Strong ETag + `Cache-Control: public, max-age=5`

### 2.2 Query Parameters

| Name    | Type   | Required | Description                                            | Constraints          |
|---------|--------|----------|--------------------------------------------------------|----------------------|
| tickers | string | yes      | CSV list of ticker symbols.                           | 1..50, ≤ 12 chars ea |

Example:

```http
GET /v2/quotes?tickers=AAPL,MSFT
