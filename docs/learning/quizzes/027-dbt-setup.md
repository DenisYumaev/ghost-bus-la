# Quiz 027 · dbt setup, the local copy, and the first models

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

Why does dbt read a local `data/` folder filled by `make dbt-sync`, instead of reading Parquet straight from S3?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Two reasons. First, readers must follow the `_SUCCESS` markers. A glob over `s3://…/dt=…/` could pick up a half-written run, or an older one awaiting deletion. Sync copies only marker-listed files, so globbing the local copy is safe. Second, S3 credentials stay out of DuckDB's `httpfs`. As a side benefit, reruns of dbt don't re-download anything. The cost is a sync step, and disk space for the days being built.

</details>

## 2. What does this do?

Why does every external source have a one-line `src_*` view in front of it?

**Your answer:**

>

<details>
<summary>Model answer</summary>

A dbt unit test replaces a model's inputs with fixture rows, and it asks the database for each input's columns to type them. An external source (a `read_parquet(...)` expression) isn't a relation dbt can inspect, so the unit test fails to compile. A view over it is a relation. dbt builds it first, and unit tests mock `ref('src_…')` like any model.

</details>

## 3. What breaks if…

…`fetch_key` used `strftime(fetched_at, …)` without `timezone('UTC', …)`?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The key would depend on the session's time zone. dbt sets UTC, but a laptop session defaults to Los Angeles, so the same row could get a different key depending on who ran the query. That happened in this PR's check: a fresh session filtered `fetched_at >= '2026-11-14'` as a Los Angeles date and every count moved by 8 hours. Converting explicitly makes the SQL mean one thing everywhere (now a rule in spec section 5).

</details>

## 4. What breaks if…

…`dim_routes.line` were just `route_short_name`?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Two of Metro's routes have no short name: the G Line (`901-13201`) and the J Line (`910-13201`), with 1,274 scheduled trips between them. Their `line` would be NULL, so a rider searching for the G Line would find nothing, and they'd drop out of every per-line number. The not-null test caught it on the first real build. The fallback takes the number before the service-change tag (`901`), which is also how Metro numbers them in `route_long_name`.

</details>

## 5. How would you change it to…

…let `make dbt` run nightly on the VM, where `data/` would grow without bound?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Sync only the days being rebuilt (the open service dates plus late-data reprocessing), and have sync delete local day folders older than the rebuild window. Gold outputs are then published to S3, the durable copy, so the local DuckDB file is a cache. Run it in a container with a memory cap, like decode (hard rule 3), and set `memory_limit` in the profile accordingly. The Airflow DAG (M4) would own the date window.

</details>
