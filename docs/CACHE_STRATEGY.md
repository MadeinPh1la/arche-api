# Cache Strategy

This document defines the canonical caching conventions for Arche.

It is **binding** for all new cache usage and should be updated whenever a new
vertical or pattern is introduced.

---

## 1. Key Naming

All cache keys follow this general pattern:

```text
arche:{vertical}:v1:{resource}:{shape}
````

* `arche` — global project namespace.
* `{vertical}` — domain vertical (e.g. `market_data`, `auth`, `refdata`).
* `v1` — cache schema version; bump if the shape/semantics change.
* `{resource}` — logical resource (e.g. `quote`, `historical`, `instrument`).
* `{shape}` — fully qualified tail that uniquely identifies the request.

### 1.1 Market Data: Latest Quotes

Latest “spot” quotes (A5 surface):

```text
arche:market_data:v1:quote:{symbol}
```

Examples:

* `arche:market_data:v1:quote:AAPL`
* `arche:market_data:v1:quote:MSFT`

Notes:

* `symbol` is always upper-cased before key construction.
* This is treated as a **hot** key (very low TTL).

### 1.2 Market Data: Historical Bars

Historical OHLCV windows (A6 surface):

```text
arche:market_data:v1:historical:{tickers_sorted}:{interval}:{from_iso}:{to_iso}:p{page}:s{page_size}
```

Where:

* `tickers_sorted` — comma-separated, upper-cased, sorted symbols.

  * Example: `AAPL,MSFT`
* `interval` — canonical `BarInterval.value` (`1min`, `1day`, etc.).
* `{from_iso}` / `{to_iso}` — full ISO-8601 timestamps.
* `page` / `page_size` — pagination parameters.

Example:

```text
arche:market_data:v1:historical:AAPL,MSFT:1day:2025-01-01T00:00:00+00:00:2025-01-31T00:00:00+00:00:p1:s100
```

If/when this tail becomes too long (e.g. complex filters), the last segment may be
replaced by a stable hash:

```text
arche:market_data:v1:historical:{tickers_sorted}:{interval}:q:{sha1(params_json)}
```

---

## 2. TTL Policy

TTL bands are defined in:

```python
arche_api.infrastructure.caching.json_cache
```

### 2.1 TTL Bands

All TTL values are in **seconds**:

* `TTL_QUOTE_HOT_S = 5`

  * Latest quotes / very hot, fast-moving data.
  * Used by `GetQuotes` for the A5 latest-quotes path.

* `TTL_INTRADAY_RECENT_S = 30`

  * Short intraday windows (e.g. last 1–2 days of bars).
  * Used by `GetHistoricalQuotesUseCase` for non-EOD intervals.

* `TTL_EOD_S = 300` (5 minutes)

  * End-of-day / older historical bars (stable but still refreshed).
  * Used by `GetHistoricalQuotesUseCase` when `interval` is daily.

* `TTL_REFERENCE_S = 3600` (1 hour)

  * Slow-moving reference/config data (identifiers, metadata, etc.).
  * Reserved for future verticals (refdata, instruments).

### 2.2 Interval → TTL Mapping (Historical Bars)

Within `GetHistoricalQuotesUseCase`:

* “EOD-like” intervals → `TTL_EOD_S`:

  * `BarInterval.I1D`, `interval.value in {"1d", "barinterval.i1d"}`, or equivalent.

* All other intervals (intraday) → `TTL_INTRADAY_RECENT_S`:

  * `1min`, `5min`, `15min`, `1hour`, etc.

---

## 3. Caching Patterns

### 3.1 Read-Through Caching (Default)

Read-through is the **default** pattern for Arche’s current read-heavy flows.

Flow:

1. Build canonical key.
2. `cache.get_json(key)`:

   * Hit → deserialize and return.
   * Miss → go to provider.
3. Call provider/gateway.
4. Store normalized payload:

   * `cache.set_json(key, payload, ttl=...)`.

Used by:

* `GetHistoricalQuotesUseCase` (historical bars)
* `GetQuotes` (latest quotes; fan-out over per-symbol keys)

A generic read-through helper is provided in:

```python
arche_api.infrastructure.caching.json_cache.read_through_json
```

### 3.2 Write-Through Caching (Not Default)

Write-through caching is **not** enabled by default and should only be used when
Arche is the system of record for a given resource (e.g. internal config).

If you introduce write-through caching:

* Document the resource and mutation surfaces.
* Keep write paths and invalidation logic in the same module/vertical.
* Do **not** mix read-through and write-through on the same keys.

---

## 4. Cache Stampede Protection

For hot keys (e.g. latest quotes, recent intraday windows), you must consider
cache stampede behavior when many workers request the same key.

`RedisJsonCache` exposes:

```python
await RedisJsonCache.get_or_set_json_singleflight(
    key,
    ttl=...,
    loader=callable,
    lock_ttl=5,
    wait_timeout=0.25,
    wait_interval=0.01,
)
```

Strategy:

1. Check cache; return on hit.
2. Build `data_key = namespace + ":" + key`.
3. Acquire lock via `SETNX {data_key}:lock EX {lock_ttl}`.

   * If lock acquired:

     * Re-check cache (in case of race).
     * Call loader.
     * Set data key with normal TTL.
     * Let lock key expire naturally.
   * If lock not acquired:

     * Spin for up to `wait_timeout`, polling cache.
     * If still empty, call loader and set cache **without** lock.

This is **best-effort** stampede protection; callers must still handle provider
errors gracefully.

---

## 5. Environment-Specific Behavior

### 5.1 Cache Backend Selection

Cache selection happens in:

```python
arche_api.dependencies.market_data._build_cache()
```

Rules:

* `ENVIRONMENT=test` or `STACKLION_TEST_MODE=1`:

  * Use in-memory `InMemoryAsyncCache` for hermetic tests.

* Otherwise:

  * Use `RedisJsonCache(namespace="arche:market_data:v1")`.

### 5.2 Gateway Selection

* Deterministic in-memory gateway (`DeterministicMarketDataGateway`) when:

  * `ENVIRONMENT=test` or `STACKLION_TEST_MODE=1`, or
  * No Marketstack access key is configured.

* Real Marketstack gateway (`MarketstackGateway`) otherwise.

---

## 6. When Adding a New Cached Feature

When you introduce a new cached feature:

1. **Define Key Shape**

   * Add the pattern here under a new subsection (e.g. “6.1 Fundamentals”).
   * Follow `arche:{vertical}:v1:{resource}:{shape}`.

2. **Pick a TTL Band**

   * Prefer one of the existing constants.
   * If you need a new band, define it in `json_cache.py` and document it here.

3. **Use Read-Through by Default**

   * Implement read-through first; only introduce write-through if strictly needed.

4. **Add Tests**

   * Assert:

     * Key shape.
     * TTL used.
     * Hit/miss semantics (e.g. gateway called once on hit).
     * Single-flight behavior if you opt into `get_or_set_json_singleflight`.

5. **Update This Document**

   * Keep this as the single source of truth for cache semantics.

````

---

## What’s next / What do you run now?

You’ve changed:

- Infra caching (`redis_client`, `json_cache`).
- Dependencies wiring (`dependencies/market_data.py`).
- Use cases (`get_quotes`, `get_historical_quotes`).
- Tests + new doc.

Next steps are straightforward:

1. **Format and lint locally**

From the repo root:

```bash
ruff check . --fix
black .
````

2. **Type-check**

```bash
python -m mypy -p arche_api -p tests
```

3. **Tests**

Either run the project’s CI script:

```bash
bash scripts/ci.sh
```

or, if you want to be explicit:

```bash
pytest -q --cov=arche_api --cov-report=term-missing
```

4. **Git hygiene**

On your feature branch:

```bash
git status
git diff  # sanity check the changes
git add -A
git commit -m "infra(caching): Standardize key/TTL strategy and add single-flight protection"
git push origin <your-branch-name>
```

5. **PR**

Open a PR against `upstream`’s target branch (probably `main`) with:

* Title along the lines of
  `infra(caching): Standardize cache keys, TTLs, and stampede protection`
* Body summarizing:

  * Key/TTL strategy
  * Read-through + single-flight implementation
  * Where caching is wired (historical + latest quotes)
  * New tests added
