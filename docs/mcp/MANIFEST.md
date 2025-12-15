
# Arche MCP Manifest

This document explains the structure and semantics of:

```text
mcp/manifest/mcp.json
````

This manifest is the **contract** between:

* The Arche MCP adapter (which calls the underlying HTTP API), and
* MCP runtimes / agents (which call methods described in this manifest).

The manifest is **descriptive only**. It does not introduce new HTTP endpoints; it documents the MCP-facing methods, their input/output schemas, and the normalized error model.

---

## File location

* **Path:** `mcp/manifest/mcp.json`
* **Format:** JSON
* **Consumers:** MCP hosts, agent frameworks, internal tooling

The manifest is intended to be machine-readable first, human-readable second. This file (`MANIFEST.md`) is the human reference for that JSON.

---

## Top-level structure

High-level layout:

```json
{
  "name": "arche-mcp",
  "version": "1.0.0",
  "description": "...",
  "contact": { ... },
  "license": { ... },
  "methods": [ ... ],
  "errors": {
    "schema": { ... }
  }
}
```

### `name`

* `"arche-mcp"`
  Stable identifier for the MCP service. Treat this as the logical service name in logs and agent configurations.

### `version`

* `"1.0.0"`
  Semantic version of the **MCP interface** (not the underlying HTTP API).

  * Bump **minor** on backwards-compatible extensions (e.g. new optional fields, new methods).
  * Bump **major** on breaking changes (e.g. removed fields, changed required fields, incompatible semantics).

### `description`

Human-readable description of what the MCP interface does:

> "Arche MCP service exposing live and historical quotes over a stable, typed interface."

Agents and UIs can display this as the service summary.

### `contact`

```json
"contact": {
  "name": "Arche API",
  "url": "https://arche.io/",
  "email": "support@arche.io"
}
```

Used by:

* Agents/UIs to surface “contact support” info.
* Internal tooling to route incidents.

### `license`

```json
"license": {
  "name": "MIT"
}
```

License for the MCP manifest/interface. This should track the overall Arche project license.

---

## Methods

The `methods` array is the core of the manifest:

```json
"methods": [
  { "name": "quotes.live", ... },
  { "name": "quotes.historical", ... },
  { "name": "system.health", ... },
  { "name": "system.metadata", ... }
]
```

Each method entry has:

* `name`: the MCP method identifier.
* `description`: human-readable explanation.
* `input_schema`: JSON Schema for call arguments.
* `result_schema`: JSON Schema for the returned object.

MCP runtimes / agents MUST treat `input_schema` and `result_schema` as authoritative.

---

### 1. `quotes.live`

**Purpose**

Fetch latest quote snapshots for up to 50 tickers.

**Schema excerpt**

```json
{
  "name": "quotes.live",
  "description": "Fetch latest quotes (snapshots) for up to 50 tickers.",
  "input_schema": {
    "type": "object",
    "required": ["tickers"],
    "additionalProperties": false,
    "properties": {
      "tickers": {
        "type": "array",
        "items": { "type": "string" },
        "minItems": 1,
        "maxItems": 50,
        "description": "Ticker symbols (case-insensitive, normalized to UPPERCASE)."
      }
    }
  },
  "result_schema": {
    "type": "object",
    "required": ["quotes"],
    "additionalProperties": false,
    "properties": {
      "quotes": {
        "type": "array",
        "items": {
          "type": "object",
          "required": ["ticker", "price", "currency", "as_of"],
          "additionalProperties": false,
          "properties": {
            "ticker": { "type": "string" },
            "price": { "type": "string", "description": "Decimal string" },
            "currency": { "type": "string" },
            "as_of": { "type": "string", "format": "date-time" },
            "volume": { "type": ["integer", "null"] }
          }
        }
      },
      "request_id": {
        "type": ["string", "null"],
        "description": "Underlying Arche X-Request-ID for correlation."
      },
      "source_status": {
        "type": "integer",
        "description": "HTTP status code returned by the underlying Arche endpoint."
      }
    }
  }
}
```

**Key points**

* `tickers`:

  * Required.
  * 1–50 entries.
  * Case-insensitive; the MCP/HTTP layer normalizes to uppercase.
* `quotes`:

  * Array of per-ticker quote objects.
  * `price` is a string to preserve decimal precision.
* `request_id`:

  * Correlation ID from the underlying HTTP call.
* `source_status`:

  * Raw HTTP status code from the underlying API (e.g. `200`, `206`).

---

### 2. `quotes.historical`

**Purpose**

Fetch historical OHLCV bars for tickers over a time window, with pagination.

**Schema excerpt**

```json
{
  "name": "quotes.historical",
  "description": "Fetch historical OHLCV bars for tickers over a time window.",
  "input_schema": {
    "type": "object",
    "required": ["tickers", "from", "to", "interval"],
    "additionalProperties": false,
    "properties": {
      "tickers": {
        "type": "array",
        "items": { "type": "string" },
        "minItems": 1,
        "maxItems": 50
      },
      "from": {
        "type": "string",
        "format": "date",
        "description": "Start date (YYYY-MM-DD, inclusive)."
      },
      "to": {
        "type": "string",
        "format": "date",
        "description": "End date (YYYY-MM-DD, inclusive)."
      },
      "interval": {
        "type": "string",
        "enum": ["1d", "1m"],
        "description": "Supported bar interval."
      },
      "page": {
        "type": "integer",
        "minimum": 1,
        "default": 1
      },
      "page_size": {
        "type": "integer",
        "minimum": 1,
        "maximum": 200,
        "default": 50
      }
    }
  },
  "result_schema": {
    "type": "object",
    "required": ["items", "page", "page_size", "total"],
    "additionalProperties": false,
    "properties": {
      "items": {
        "type": "array",
        "items": {
          "type": "object",
          "required": [
            "ticker",
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "interval"
          ],
          "additionalProperties": false,
          "properties": {
            "ticker": { "type": "string" },
            "timestamp": { "type": "string", "format": "date-time" },
            "open": { "type": "string" },
            "high": { "type": "string" },
            "low": { "type": "string" },
            "close": { "type": "string" },
            "volume": { "type": ["string", "null"] },
            "interval": { "type": "string" }
          }
        }
      },
      "page": { "type": "integer" },
      "page_size": { "type": "integer" },
      "total": { "type": "integer" },
      "request_id": {
        "type": ["string", "null"],
        "description": "Underlying Arche X-Request-ID for correlation."
      },
      "source_status": { "type": "integer" }
    }
  }
}
```

**Key points**

* `tickers`:

  * Same constraints as `quotes.live`: 1–50 symbols.
* `from` / `to`:

  * Dates only, `YYYY-MM-DD`, inclusive.
* `interval`:

  * Currently `"1d"` (daily) or `"1m"` (1-minute).
  * Agents should treat this list as authoritative and **not** assume additional intervals.
* Pagination:

  * `page`: 1-based page number, default `1`.
  * `page_size`: 1–200, default `50`.
* Result:

  * `items`: OHLCV bars.
  * `timestamp`: ISO-8601 datetime.
  * `open`/`high`/`low`/`close`/`volume`: strings to preserve precision and avoid float issues.
  * `total`: total number of bars across all pages.

---

### 3. `system.health`

**Purpose**

Simple health indicator for the Arche API via MCP.

**Schema excerpt**

```json
{
  "name": "system.health",
  "description": "Simple health indicator for the Arche API via MCP.",
  "input_schema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {}
  },
  "result_schema": {
    "type": "object",
    "required": ["status"],
    "additionalProperties": false,
    "properties": {
      "status": { "type": "string", "enum": ["ok", "degraded", "down"] },
      "request_id": { "type": ["string", "null"] },
      "source_status": { "type": "integer" }
    }
  }
}
```

**Key points**

* No input properties; call with an empty object.
* `status`:

  * `"ok"`, `"degraded"`, or `"down"`:

    * Surface-level signal for agent health checks.
* `request_id`:

  * Same correlation semantics as other methods.
* `source_status`:

  * Underlying HTTP status code for the health probe.

---

### 4. `system.metadata`

**Purpose**

Static metadata about Arche MCP capabilities and usage limits.

**Schema excerpt**

```json
{
  "name": "system.metadata",
  "description": "Static metadata about Arche MCP capabilities and usage limits.",
  "input_schema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {}
  },
  "result_schema": {
    "type": "object",
    "required": [
      "mcp_version",
      "api_version",
      "quotes_contract_version",
      "supported_intervals",
      "max_page_size",
      "max_range_days",
      "max_tickers_per_request"
    ],
    "additionalProperties": false,
    "properties": {
      "mcp_version": { "type": "string" },
      "api_version": { "type": "string" },
      "quotes_contract_version": { "type": "string" },
      "supported_intervals": {
        "type": "array",
        "items": { "type": "string" }
      },
      "max_page_size": { "type": "integer" },
      "max_range_days": { "type": "integer" },
      "max_tickers_per_request": { "type": "integer" }
    }
  }
}
```

**Key points**

This method is the **single source of truth** for:

* `mcp_version`:

  * Version of the MCP interface (should track `mcp.json` `version`).
* `api_version`:

  * Version of the underlying HTTP API (e.g. `"v1"`).
* `quotes_contract_version`:

  * Version of the quotes DTO / contract.
* `supported_intervals`:

  * List of intervals currently supported by `quotes.historical`.
* `max_page_size`:

  * Upper bound for `page_size`.
* `max_range_days`:

  * Maximum allowed date span for historical queries.
* `max_tickers_per_request`:

  * Upper bound for `tickers` length (must match method schemas).

Agents should **use this method** instead of hardcoding limits.

---

## Error model

The `errors` section defines the **MCP-level error object**:

```json
"errors": {
  "schema": {
    "type": "object",
    "required": ["type", "message", "retryable"],
    "additionalProperties": false,
    "properties": {
      "type": {
        "type": "string",
        "description": "Stable error type (e.g. VALIDATION_ERROR, RATE_LIMITED)."
      },
      "message": { "type": "string" },
      "retryable": { "type": "boolean" },
      "http_status": { "type": ["integer", "null"] },
      "http_code": { "type": ["string", "null"] },
      "trace_id": { "type": ["string", "null"] },
      "retry_after_s": { "type": ["number", "null"] }
    }
  }
}
```

**Field semantics**

* `type`:

  * Stable, machine-friendly error type.
  * Examples: `VALIDATION_ERROR`, `RATE_LIMITED`, `UPSTREAM_ERROR`.
* `message`:

  * Human-readable message safe for user display.
* `retryable`:

  * Whether the operation is safe to retry automatically.
* `http_status`:

  * Underlying HTTP status code (e.g. `400`, `429`, `500`), when available.
* `http_code`:

  * Optional textual code / phrase (e.g. `"Bad Request"`).
* `trace_id`:

  * Correlation/trace ID, typically mapped from the underlying `X-Request-ID` or error envelope.
* `retry_after_s`:

  * Recommended backoff duration in seconds, especially for rate-limit scenarios.

MCP adapters should map the underlying HTTP error contract into this shape consistently.

---

## Versioning and change control

When you change **anything** in the manifest that affects clients:

* Add/remove methods.
* Change required fields.
* Change field types or semantics.
* Change error shape.

You must:

1. Bump the manifest `version` following semver.
2. Update `system.metadata.mcp_version` to match.
3. Update this `MANIFEST.md` and `docs/mcp/README.md` to reflect the new behavior.
4. Run full CI (lint, type-check, tests) to keep the MCP layer aligned with the core Arche platform.

The goal is to keep the MCP interface predictable and stable for agents, with clear, explicit contracts instead of guesswork.

