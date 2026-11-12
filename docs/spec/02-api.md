# 02 · API, auth, and database

FastAPI service used by the web app and open to the public. Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 with psycopg 3, Alembic, PostgreSQL 16.

## 1. Conventions

- Base URL `https://api.<domain>/v1`. Breaking changes get `/v2`; additive changes don't.
- JSON, `snake_case` keys. Timestamps are ISO 8601 in UTC with `Z`. Local times that are meaningful to riders are also returned as `HH:MM` strings in `America/Los_Angeles` and labeled `_local`.
- A **line** is identified by its public number as a string (`"720"`), taken from `route_short_name`. Stops use GTFS `stop_id`. Directions use `direction_id` (0 or 1) and always come with a `headsign`.
- Rates are fractions between 0 and 1, never percentages. Every rate comes with `n_trips` and, when available, `ci_low` and `ci_high`. A suppressed cell returns `"suppressed": true` and null rates.
- Every response carries `X-Request-Id`. Logs include it.
- Every data response includes `data_as_of` (when the serving table was last published).
- The OpenAPI document is served at `/v1/openapi.json`, with docs at `/v1/docs`. Every endpoint has a summary, a description, and an example.

## 2. Errors

RFC 9457 problem details, `Content-Type: application/problem+json`:

```json
{
  "type": "https://<domain>/problems/not-found",
  "title": "Line not found",
  "status": 404,
  "detail": "No Metro-operated line '999'.",
  "request_id": "01JCA…"
}
```

| Status | When |
| --- | --- |
| 400 | Malformed parameters |
| 401 | No valid session on a protected route |
| 403 | Origin check failed, or the resource belongs to another user |
| 404 | Unknown line, stop, or resource |
| 409 | Duplicate commute |
| 422 | Validation error; `errors` lists fields |
| 429 | Rate limited; `Retry-After` set |
| 503 | Database unavailable or serving data older than 60 minutes on `/readyz` |

Never return a stack trace. Never reveal whether an email has an account.

## 3. Pagination, caching, rate limits, CORS

- **Pagination:** cursor-based on list endpoints that can grow (`/trips/outcomes`, `/alerts`). `?limit=` (default 50, max 200) and `?cursor=`. The response has `next_cursor` or null. Cursors are opaque, base64 of the last sort key. No offset pagination.
- **HTTP caching:** public data endpoints send `Cache-Control: public, max-age=300, stale-while-revalidate=600` and an `ETag` derived from `data_as_of` plus the query. Honor `If-None-Match` with 304. Authenticated endpoints send `Cache-Control: no-store`.
- **In-process cache:** TTL cache (5 minutes, keyed by route and parameters) in front of serving queries; cleared when `ops.publish_run` advances.
- **Rate limits:** anonymous 60 requests/minute per IP; authenticated 120/minute per user; auth endpoints stricter (section 5). In-memory limiter; fine for one instance (ADR-014).
- **CORS:** allow only the web origin(s), with credentials. No wildcard.

## 4. Endpoints

### 4.1 Public data

| Method and path | Purpose |
| --- | --- |
| `GET /v1/lines` | All Metro-operated lines with headline reliability (28-day window) |
| `GET /v1/lines/{line}` | Line detail: name, directions with headsigns, summary rates |
| `GET /v1/lines/{line}/stops?direction_id=` | Ordered stops for a direction |
| `GET /v1/lines/{line}/reliability?direction_id=&window=&day_type=` | Hour-by-day-type grid of rates |
| `GET /v1/lines/{line}/stops/{stop_id}/reliability?direction_id=&window=` (P1) | Same, at one stop |
| `GET /v1/lines/{line}/trend?direction_id=&weeks=` | Weekly missed, announced, and unplanned rates |
| `GET /v1/cancellations/current?line=` | Currently announced cancellations |
| `GET /v1/flags/current?line=` (P1) | Trips flagged likely missing right now, with the detector version and its measured precision. Always labeled an estimate |
| `GET /v1/trips/outcomes?line=&service_date=&cursor=` | Trip-level outcomes for one line and date |
| `GET /v1/system/summary` | Headline numbers, counts, date range |
| `GET /v1/system/feed-health?hours=` | Feed status for the status page |
| `GET /v1/meta/method` | Thresholds and definitions currently in force |

`window` is `28d` (default), `90d`, or `all`. `day_type` is `weekday`, `saturday`, or `sunday`.

Example, `GET /v1/lines/720/reliability?direction_id=0&window=28d`:

```json
{
  "line": "720",
  "direction_id": 0,
  "headsign": "Santa Monica",
  "window": "28d",
  "data_as_of": "2026-12-01T17:40:12Z",
  "cells": [
    {
      "day_type": "weekday",
      "hour_local": 17,
      "n_trips": 412,
      "missed_rate": 0.051,
      "announced_rate": 0.024,
      "unplanned_rate": 0.027,
      "ci_low": 0.038,
      "ci_high": 0.066,
      "suppressed": false
    }
  ],
  "method_url": "https://<domain>/method"
}
```

The numbers in this example are illustrative.

### 4.2 Auth

| Method and path | Purpose |
| --- | --- |
| `POST /v1/auth/magic-link` | Body `{email}`. Always returns 202 |
| `POST /v1/auth/verify` | Body `{token}`. Sets the session cookie |
| `POST /v1/auth/logout` | Clears the session |
| `GET /v1/me` | Current user |
| `DELETE /v1/me` | Deletes the account and all commutes; cancels pending alerts |

### 4.3 Commutes and alerts (session required)

| Method and path | Purpose |
| --- | --- |
| `GET /v1/commutes` | List the user's commutes |
| `POST /v1/commutes` | Create |
| `PATCH /v1/commutes/{id}` | Update or pause |
| `DELETE /v1/commutes/{id}` | Delete |
| `GET /v1/commutes/{id}/reliability` (P1) | Reliability for this commute's window |
| `GET /v1/alerts?cursor=` | Alert history |
| `POST /v1/unsubscribe` | Body `{token}`; no session needed. Pauses one commute or all |
| `POST /v1/alerts/feedback` (P1) | Body `{token, useful}`; signed token from the alert email, no session needed. One answer per alert |

`POST /v1/commutes` body:

```json
{
  "label": "Morning to work",
  "line": "720",
  "direction_id": 0,
  "stop_id": "5397",
  "days_of_week": [0, 1, 2, 3, 4],
  "window_start_local": "07:15",
  "window_end_local": "08:00"
}
```

Validation: the line is Metro-operated; the stop belongs to that line and direction in the schedule version in force; `days_of_week` uses 0 for Monday through 6 for Sunday; the window is at least 10 minutes and at most 4 hours and doesn't cross midnight (a rider who needs that creates two commutes); at most 10 commutes per user.

### 4.4 Operations

| Path | Purpose |
| --- | --- |
| `GET /healthz` | Process is up. No dependencies checked |
| `GET /readyz` | Database reachable and serving data under 60 minutes old |
| `GET /metrics` | Prometheus metrics; reachable only from inside the VM network |

## 5. Authentication

Passwordless email links with server-side sessions (ADR-009, ADR-010).

### 5.1 Flow

1. The rider submits an email. The API always answers 202 with the same body, whether or not the email exists.
2. The API generates a 32-byte random token, stores only its SHA-256 hash with a 15-minute expiry, and emails `https://<domain>/auth/verify#token=<token>`.
3. The link opens a web page. The page reads the token from the URL fragment and sends `POST /v1/auth/verify`. **A plain GET must not log anyone in:** email security scanners follow links, and a GET would consume the single-use token before the rider clicks. The fragment also keeps the token out of server logs and referrers.
4. The API checks hash, expiry, and unused status; marks the token consumed; creates the user if new; creates a session; sets the cookie.

### 5.2 Sessions

- Opaque 32-byte session ID; store only its hash. Cookie attributes: `HttpOnly; Secure; SameSite=Lax; Path=/; Domain=<parent domain>`.
- 30-day sliding expiry; `last_seen_at` updated at most once per hour.
- Logout deletes the row. Account deletion deletes all sessions.

### 5.3 Abuse controls

- Magic-link requests: 3 per email per hour, 10 per IP per hour. Excess requests still return 202 but send nothing.
- State-changing requests must carry `Content-Type: application/json` and an `Origin` header matching the allowlist; otherwise 403. With `SameSite=Lax` this covers CSRF for this app.
- Tokens and session IDs are compared with constant-time functions and never logged.

### 5.4 Unsubscribe

Every alert email carries a signed link (HMAC over commute ID, user ID, and scope, with a server secret) and the headers `List-Unsubscribe` and `List-Unsubscribe-Post: List-Unsubscribe=One-Click`. One click pauses the commute without login.

## 6. Postgres: `app` schema

Managed by Alembic. Migrations must be backward compatible with the previous release (expand, deploy, contract), because deploys aren't atomic.

```sql
create extension if not exists citext;
create extension if not exists pgcrypto;
create schema app;

create table app.users (
  id                uuid primary key default gen_random_uuid(),
  email             citext not null unique,
  email_verified_at timestamptz,
  locale            text not null default 'en',
  created_at        timestamptz not null default now()
);

create table app.magic_link (
  token_hash  bytea primary key,
  email       citext not null,
  request_ip  inet,
  created_at  timestamptz not null default now(),
  expires_at  timestamptz not null,
  consumed_at timestamptz
);
create index on app.magic_link (email, created_at);

create table app.session (
  id_hash      bytea primary key,
  user_id      uuid not null references app.users on delete cascade,
  created_at   timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  expires_at   timestamptz not null
);
create index on app.session (user_id);

create table app.commute (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references app.users on delete cascade,
  label         text not null default '',
  line          text not null,
  direction_id  smallint not null check (direction_id in (0, 1)),
  stop_id       text not null,
  days_of_week  smallint[] not null check (days_of_week <@ array[0,1,2,3,4,5,6]::smallint[]
                                           and cardinality(days_of_week) between 1 and 7),
  window_start  time not null,
  window_end    time not null check (window_end > window_start),
  active        boolean not null default true,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (user_id, line, direction_id, stop_id, window_start, window_end)
);
create index commute_match_idx on app.commute (line, direction_id) where active;

create table app.cancellation_event (
  id              bigint generated always as identity primary key,
  source          text not null check (source in ('trip_update')),
  source_key      text not null,
  service_date    date not null,
  line            text not null,
  direction_id    smallint,
  trip_id         text,
  scheduled_start timestamptz,
  first_seen_at   timestamptz not null,
  last_seen_at    timestamptz not null,
  withdrawn_at    timestamptz,
  raw             jsonb not null,
  unique (source, source_key, service_date)
);
create index on app.cancellation_event (line, service_date);
create index on app.cancellation_event (last_seen_at) where withdrawn_at is null;

create table app.alert_outbox (
  id                    bigint generated always as identity primary key,
  user_id               uuid not null references app.users on delete cascade,
  commute_id            uuid not null references app.commute on delete cascade,
  cancellation_event_id bigint not null references app.cancellation_event,
  alert_type            text not null check (alert_type in ('announced_cancellation', 'likely_missing', 'reinstated')),
  dedupe_key            text not null unique,
  status                text not null default 'pending'
                        check (status in ('pending', 'sending', 'sent', 'failed', 'dead', 'suppressed')),
  suppress_reason       text,
  attempts              int not null default 0,
  next_attempt_at       timestamptz not null default now(),
  stop_departure_at     timestamptz not null,
  payload               jsonb not null,
  provider_message_id   text,
  last_error            text,
  created_at            timestamptz not null default now(),
  sent_at               timestamptz
);
create index alert_outbox_due_idx on app.alert_outbox (next_attempt_at)
  where status in ('pending', 'failed');
create index on app.alert_outbox (user_id, created_at desc);

-- P1: likely-missing flags from the baseline detector (ADR-005; alerts spec, section 8)
create table app.ghost_flag (
  id               bigint generated always as identity primary key,
  trip_id          text not null,
  service_date     date not null,
  line             text not null,
  direction_id     smallint,
  scheduled_start  timestamptz not null,
  detector_version text not null,
  event_type       text not null check (event_type in ('flag', 'retract')),
  emitted_at       timestamptz not null default now(),
  unique (trip_id, service_date, detector_version, event_type)
);
create index on app.ghost_flag (service_date, line);
```

Notes for the build:

- Account deletion is a hard delete; `on delete cascade` removes commutes, sessions, and outbox rows. Keep only anonymous aggregate counts.
- `dedupe_key` is `<commute_id>:<cancellation_event_id>:<alert_type>`. The unique constraint is what guarantees one alert per commute per event.
- Purge consumed or expired `magic_link` rows daily; purge expired sessions daily.

## 7. Postgres: `serving` and `ops` schemas

`serving` tables are written only by `publish` (atomic swap, pipeline spec section 13) and read only by the API and detector.

| Table | Grain | Used by |
| --- | --- | --- |
| `serving.line` | line | Line list and detail |
| `serving.line_direction` | line × direction | Headsigns |
| `serving.line_stop` | line × direction × stop sequence | Stop pickers, validation |
| `serving.trip_stop_time` | schedule version × trip × stop sequence | Commute matching; index on (`trip_id`, `stop_id`) |
| `serving.schedule_version` | version | Version in force |
| `serving.reliability` | line × direction × day type × hour × window | Reliability grid |
| `serving.stop_reliability` (P1) | adds stop | Stop view |
| `serving.line_trend` | line × direction × week | Trend chart |
| `serving.trip_outcome_recent` | trip × service date, last 35 days | Trip list |
| `serving.system_summary` | window | Home page |
| `serving.feed_health` | feed × 5 minutes, last 7 days | Status page |

`ops` tables: `ops.publish_run`, `ops.consumer_cursor` (detector position), `ops.feed_status` (latest success per feed, written by the detector and pipeline, never by `ingest`), `ops.deploy` (git SHA, time), `ops.alert_feedback` (outbox ID, useful yes or no, time; P1).

Index every serving table on exactly the columns its endpoint filters by, and confirm each endpoint's query plan with `EXPLAIN ANALYZE` in M5. Record the plans in `docs/perf/`.

## 8. Performance budgets

| Measure | Budget | How it is checked |
| --- | --- | --- |
| p95 latency, public data endpoints, at the origin | ≤ 200 ms at 50 requests/s | k6 script `tests/load/public_read.js`, report committed to `docs/perf/` |
| p99 latency | ≤ 500 ms | Same |
| Error rate under load | < 0.1% | Same |
| `POST /v1/commutes` p95 | ≤ 300 ms | k6 |
| Cold start to ready | ≤ 10 s | Deploy script |

Run the load test from a machine outside the VM against production during a quiet hour, with a clearly labeled user agent. Record instance type, dataset size, and git SHA with every report, so the numbers are honest.

## 9. Testing

- **Unit:** validators, cursor encoding, ETag logic, rate limiter, token and cookie handling.
- **Integration:** real Postgres in Docker (`compose.test.yml`); every endpoint's success and error paths; auth flow including a prefetch-style GET that must not log in; ownership checks (user A can't read or change user B's commute).
- **Contract:** the OpenAPI document is generated in CI and diffed against the committed copy; an unintended API change fails the build. The web app's TypeScript client is generated from it.
- **Migration:** apply all migrations to an empty database, and from the previous release's schema, in CI.
- **Property-based (Hypothesis):** cursor round-trips; commute window validation.

## 10. Code layout (`services/api/`)

```text
api/
├── main.py            # app factory, middleware, exception handlers
├── deps.py            # db session, current user, rate limiter
├── routers/           # lines.py, cancellations.py, trips.py, system.py, auth.py, commutes.py, alerts.py
├── schemas/           # Pydantic request/response models
├── repos/             # SQL access, one module per table group; no SQL in routers
├── security/          # tokens, sessions, origin check, unsubscribe signing
├── cache.py  etag.py  problems.py  settings.py
├── migrations/        # Alembic
└── tests/
```

Routers hold no business logic and no SQL. Repositories return plain rows; schemas shape the response.
