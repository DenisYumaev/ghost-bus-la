# ADR-013: Sync FastAPI endpoints with a connection pool, served by uvicorn

- **Status:** Accepted
- **Date:** 2026-11-18
- **Supersedes:** nothing. Writes up the planned decision in `docs/SPEC.md` section 5 (row 013). Adds uvicorn, the ASGI server, which the stack list doesn't name.
- **Evidence:**
  - Every public endpoint is one indexed lookup in a small `serving` table (ADR-007): `reliability` has about 25,000 rows today and `line_summary` about 1,000, from the real warehouse published in PR #44.
  - The budget is p95 ≤ 200 ms at 50 requests/s at the origin (API spec section 8), checked by the M5 load test.

## Context

FastAPI runs both `def` endpoints, in a thread pool, and `async def` endpoints, on the event loop. The API's work is short database reads. There is one instance on one VM (ADR-011), with Postgres in the same Docker network.

## Decision

1. **Endpoints are plain `def` functions** using SQLAlchemy 2 Core with psycopg 3, through a pooled engine (`pool_size` 5, `max_overflow` 5, `pool_pre_ping`). No ORM: repositories return rows and Pydantic shapes the response (API spec section 10).
2. **Server-side timeouts on every API connection:**
   - `statement_timeout` 5 s, so a runaway query can't hold a worker;
   - `idle_in_transaction_session_timeout` 10 s, so a connection that forgot to end its transaction can't hold `serving` table locks.

   The publish swap waits for exactly those locks (ADR-007; its own `lock_timeout` is the other half).
3. **Reads run at READ COMMITTED in short transactions**, one per request, ended before the response is sent.
4. **Server:** uvicorn, run by the API container in M2's deploy work.

## Why

- **Simpler to debug.** A synchronous call stack is an ordinary Python traceback, and SQLAlchemy's sync API is the well-trodden path.
- **Enough concurrency.** A 40-thread pool doing millisecond lookups covers 50 requests/s with room to spare. The M5 load test proves it either way.
- **uvicorn** is what FastAPI's own documentation runs it with. The alternatives (hypercorn, daphne) add nothing here.

## Alternatives considered

- **Async everywhere** (`async def` with an async driver): more concurrency per process, which this load doesn't need. It makes every call site and test async, and a blocking call in the wrong place stalls everything.
- **Gunicorn with uvicorn workers:** several processes for one small VM. One uvicorn process is enough until the load test says otherwise.

## Consequences

- The thread pool and the database pool must be sized together. If the load test shows queueing, raise both.
- The in-process TTL cache (ADR-014, M5) slots in front of the repositories without changing endpoints.

## Would change if

- The M5 load test misses the p95 budget because of threading, not queries: async endpoints for the hot routes (SPEC section 5).
