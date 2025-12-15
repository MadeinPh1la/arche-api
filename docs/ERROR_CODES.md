# Arche Error Codes

Canonical error envelope:
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "http_status": 422,
    "message": "Request validation failed",
    "details": [],
    "trace_id": "uuid"
  }
}

| Code             | HTTP | Meaning                           | Notes                                 |
| ---------------- | ---- | --------------------------------- | ------------------------------------- |
| VALIDATION_ERROR | 422  | Request failed schema/constraints | Pydantic / adapters-level validation  |
| UNAUTHORIZED     | 401  | Missing/invalid auth              | Token invalid/expired, no credentials |
| FORBIDDEN        | 403  | Authenticated but not allowed     | Entitlements/plan gating              |
| NOT_FOUND        | 404  | Resource doesn’t exist            |                                       |
| RATE_LIMITED     | 429  | Too many requests                 | Include `Retry-After` + X-RateLimit-* |
| INTERNAL_ERROR   | 500  | Unexpected server error           | Do not leak internals                 |
