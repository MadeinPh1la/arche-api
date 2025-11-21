# Stacklion MCP Integration

Stacklion exposes a **Model Context Protocol (MCP)** interface on top of the public Stacklion API so AI agents and MCP runtimes can:

- Discover available methods and their input/output schemas.
- Understand authentication and rate-limit expectations.
- Consume stable, typed responses and errors.
- Correlate MCP calls with underlying HTTP requests via request IDs.

The MCP layer is a **thin adapter** over the existing HTTP contracts defined in:

- `docs/standards/API_STANDARDS.md`
- `docs/standards/ENGINEERING_GUIDE.md`
- `docs/standards/DEFINITION_OF_DONE.md`

The HTTP layer uses Stacklion’s canonical envelopes (e.g. `SuccessEnvelope`, `PaginatedEnvelope`, `ErrorEnvelope`). The MCP layer **unwraps** those into the `result_schema` and `errors.schema` types defined in `mcp/manifest/mcp.json`.

---

## Surface area

The MCP manifest currently defines four methods:

- `quotes.live`  
  Fetch latest quote snapshots for up to 50 tickers.

- `quotes.historical`  
  Fetch historical OHLCV bars for one or more tickers over a time window (paginated).

- `system.health`  
  Cheap health indicator for the Stacklion API via MCP.

- `system.metadata`  
  Static metadata about MCP/interface versions and usage limits (intervals, page size, range constraints, etc.).

The shared MCP error model is described under `errors.schema` in `mcp/manifest/mcp.json`.

---

## Where the manifest lives

The MCP manifest is checked into the repo at:

- `mcp/manifest/mcp.json`

At runtime you typically either:

- Mount this file into MCP host/agent container, or
- Serve it as static JSON from deployment and point the MCP host at that URL.

MCP runtimes should treat the manifest as the **single source of truth** for:

- Method names and descriptions.
- Input/output JSON Schemas.
- Error object shape.

Additional HTTP-level details (base URL, auth headers, rate-limit headers) come from deployment config and API standards.

---

## Authentication

All MCP calls must be authenticated against the underlying Stacklion API.

### Primary mechanism

The MCP layer is expected to send an API key with each HTTP call, typically via:

```http
X-Api-Key: <stacklion_api_key>
````

If deployment uses a different header or mechanism, document that at the environment level and configure the MCP host accordingly.

### Optional user-level auth

Some deployments may also require a user-level bearer token:

```http
Authorization: Bearer <jwt_token>
```

The MCP manifest itself does **not** enforce auth; it documents the method schemas. The actual auth story is enforced at the HTTP layer according to API standards.

---

## Rate limiting

Rate limiting is enforced at the HTTP layer (not directly in the manifest):

* Budgets are typically per API key and/or per client identity.
* When a limit is exceeded, the HTTP API returns `429 Too Many Requests` with:

  * A canonical `ErrorEnvelope` body.
  * Standard rate-limit headers (for example: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, `Retry-After`).

The MCP adapter is responsible for:

* Mapping 429 responses into an MCP error with:

  * `type` (e.g. `RATE_LIMITED`)
  * `retryable: true`
  * `retry_after_s` based on `Retry-After` / reset time.
* Preserving any `trace_id` / `X-Request-ID` so clients can correlate requests.

Agents should **back off** according to `retry_after_s` rather than hammering the endpoint.

---

## HTTP vs MCP shapes

### HTTP layer (underlying API)

The Stacklion HTTP API uses envelope contracts like:

* `SuccessEnvelope[T]`
* `PaginatedEnvelope[T]`
* `ErrorEnvelope`

These are defined in `docs/standards/API_STANDARDS.md` and represented in OpenAPI.

Example (conceptual):

```json
{
  "data": {
    "quotes": [
      { "symbol": "AAPL", "price": "225.12", "currency": "USD", "as_of": "2025-11-21T15:30:05Z" }
    ]
  }
}
```

### MCP layer (what agents see)

The MCP layer unwraps those envelopes and normalizes responses to the `result_schema` defined per method in `mcp/manifest/mcp.json`.

Example MCP `quotes.live` result:

```json
{
  "quotes": [
    {
      "ticker": "AAPL",
      "price": "225.12",
      "currency": "USD",
      "as_of": "2025-11-21T15:30:05Z",
      "volume": 15300432
    }
  ],
  "request_id": "c5a6a0c4-0c8d-4f0f-b6e6-8f1f0c2b7e7a",
  "source_status": 200
}
```

### MCP error object

The manifest’s `errors.schema` describes the normalized MCP error object, for example:

```json
{
  "type": "VALIDATION_ERROR",
  "message": "interval must be one of ['1d', '1m']",
  "retryable": false,
  "http_status": 400,
  "http_code": "Bad Request",
  "trace_id": "7e8a5d2e-2f8e-4a7a-8d2b-0e1f9e5c1234",
  "retry_after_s": null
}
```

This is derived from the underlying `ErrorEnvelope` plus HTTP response metadata.

---

## Method examples

### 1. `quotes.live`

**Purpose**

Fetch latest quote snapshots for up to 50 tickers.

**Input schema (from manifest)**

```json
{
  "type": "object",
  "required": ["tickers"],
  "additionalProperties": false,
  "properties": {
    "tickers": {
      "type": "array",
      "items": { "type": "string" },
      "minItems": 1,
      "maxItems": 50
    }
  }
}
```

**Example MCP call**

```json
{
  "method": "quotes.live",
  "arguments": {
    "tickers": ["AAPL", "MSFT", "GOOG"]
  }
}
```

**Example MCP result**

```json
{
  "quotes": [
    {
      "ticker": "AAPL",
      "price": "225.12",
      "currency": "USD",
      "as_of": "2025-11-21T15:30:05Z",
      "volume": 15300432
    },
    {
      "ticker": "MSFT",
      "price": "420.02",
      "currency": "USD",
      "as_of": "2025-11-21T15:30:05Z",
      "volume": 11003211
    }
  ],
  "request_id": "c5a6a0c4-0c8d-4f0f-b6e6-8f1f0c2b7e7a",
  "source_status": 200
}
```

---

### 2. `quotes.historical`

**Purpose**

Fetch historical OHLCV bars for tickers over a date range, with pagination.

**Input schema (from manifest)**

```json
{
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
    "from": { "type": "string", "format": "date" },
    "to": { "type": "string", "format": "date" },
    "interval": { "type": "string", "enum": ["1d", "1m"] },
    "page": { "type": "integer", "minimum": 1, "default": 1 },
    "page_size": { "type": "integer", "minimum": 1, "maximum": 200, "default": 50 }
  }
}
```

**Example MCP call**

```json
{
  "method": "quotes.historical",
  "arguments": {
    "tickers": ["MSFT"],
    "from": "2024-01-01",
    "to": "2024-01-31",
    "interval": "1d",
    "page": 1,
    "page_size": 50
  }
}
```

**Example MCP result**

```json
{
  "items": [
    {
      "ticker": "MSFT",
      "timestamp": "2024-01-02T00:00:00Z",
      "open": "362.10",
      "high": "365.50",
      "low": "360.90",
      "close": "364.20",
      "volume": "15300000",
      "interval": "1d"
    }
  ],
  "page": 1,
  "page_size": 50,
  "total": 22,
  "request_id": "7e8a5d2e-2f8e-4a7a-8d2b-0e1f9e5c1234",
  "source_status": 200
}
```

---

### 3. `system.health`

**Purpose**

Simple health indicator for the Stacklion API via MCP.

**Input schema**

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {}
}
```

**Example MCP call**

```json
{
  "method": "system.health",
  "arguments": {}
}
```

**Example MCP result**

```json
{
  "status": "ok",
  "request_id": "health-98e311e1-7d8b-4e2e-9b49-5a17857e2f30",
  "source_status": 200
}
```

---

### 4. `system.metadata`

**Purpose**

Expose MCP-level metadata and limits so agents can self-tune behavior (batch sizes, ranges, etc.).

**Input schema**

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {}
}
```

**Example MCP result**

```json
{
  "mcp_version": "1.0.0",
  "api_version": "v1",
  "quotes_contract_version": "2025-11-01",
  "supported_intervals": ["1d", "1m"],
  "max_page_size": 200,
  "max_range_days": 365,
  "max_tickers_per_request": 50
}
```

Use these values instead of hardcoding limits in agents.

---

## Quickstart for MCP hosts

1. **Load the manifest**

   Configure MCP host to read:

   ```text
   mcp/manifest/mcp.json
   ```

   either from the filesystem or from a static URL in deployment.

2. **Wire auth**

   * Ensure an API key is available (e.g. environment variable).
   * Inject `X-Api-Key` on every HTTP call the MCP host makes to Stacklion.
   * If environment requires bearer tokens, also attach `Authorization: Bearer <JWT>`.

3. **Call methods**

   * Validate arguments against `input_schema` before calling.
   * Map arguments into query parameters or JSON bodies according to MCP adapter.
   * Parse responses into `result_schema`.
   * Normalize errors according to `errors.schema`.

4. **Respect limits**

   * Read `max_tickers_per_request`, `max_page_size`, and `max_range_days` from `system.metadata`.
   * Honor `retry_after_s` on MCP errors (especially `RATE_LIMITED`).

---

## Keeping things in sync

When we change:

* A method’s inputs or outputs,
* Usage limits (page size, max range, max tickers),
* Error codes or shapes,

we must:

1. Update the underlying HTTP contract (routers, DTOs, envelopes).
2. Update `mcp/manifest/mcp.json` to match.
3. Update the examples in this `README.md` if they drift.
4. Run CI (lint, mypy, tests, contract checks) before merge.

This keeps the MCP interface production-grade: predictable, typed, and fully aligned with the core Stacklion platform.

