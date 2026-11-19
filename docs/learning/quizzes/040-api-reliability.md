# Quiz 040 · The API and the reliability endpoint

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

A browser repeats `GET /v1/lines/720/reliability?direction_id=0` with `If-None-Match: "<tag from last time>"`, and nothing has been published since.

**Your answer:**

>

<details>
<summary>Model answer</summary>

The ETag is a hash of `data_as_of` (the last successful publish of `reliability`) plus the path and query. Nothing was published, so the tag is the same, and the API answers 304 with no body: the browser reuses its copy. The API still runs the small lookups to find the line and `data_as_of`, but skips the grid query and the JSON.

</details>

## 2. What does this do?

Why does every API connection set `idle_in_transaction_session_timeout`?

**Your answer:**

>

<details>
<summary>Model answer</summary>

A connection that reads `serving.reliability` and never ends its transaction holds a share lock on that table until it does. The publish swap needs an exclusive lock, and while it waits, every new reader queues behind it. Ending idle transactions after 10 s caps that. publish's own 2 s `lock_timeout` with retries is the other half of the defence.

</details>

## 3. What breaks if…

…the router built its SQL with an f-string containing `line`?

**Your answer:**

>

<details>
<summary>Model answer</summary>

`line` comes from the URL, so `/v1/lines/2'; DROP TABLE serving.line; --/reliability` would be SQL injection. Hard rule 7 keeps SQL in repositories, always parameterized (`:slug`, `:line`), so the database receives values separately from the SQL text. Routers hold no SQL at all.

</details>

## 4. What breaks if…

…the line were looked up in the newest schedule version instead of the one in force today?

**Your answer:**

>

<details>
<summary>Model answer</summary>

When Metro publishes a schedule in advance, the newest version starts in the future. A line it drops would 404 while it is still running, and a new line would appear before it exists. The repository picks the newest version that starts on or before today's Los Angeles date.

</details>

## 5. How would you change it to…

…serve `GET /v1/lines` (every line with its 28-day headline)?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Add a repository query joining `serving.line` (version in force) with `serving.line_summary` where `time_window = '28d' AND direction_id IS NULL`. The index on (`time_window`, `direction_id`) serves it. Order by `line_number`, then `line`. Same ETag pattern, keyed on the later of the two tables' `data_as_of`. A Pydantic list model goes in `schemas/`, and the router stays SQL-free.

</details>
