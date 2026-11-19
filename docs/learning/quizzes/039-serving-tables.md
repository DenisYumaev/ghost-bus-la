# Quiz 039 · Serving tables and `make publish`

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

`SELECT * FROM fct_trip_outcomes WHERE service_date > (SELECT max(service_date) FROM fct_trip_outcomes) - 35`

**Your answer:**

>

<details>
<summary>Model answer</summary>

It keeps the newest 35 service dates of trip outcomes for `serving.trip_outcome_recent`, counting back from the newest date in the data, not from today. If the pipeline stalls for three days, the table still holds 35 days of data, not 32. A rebuild of the same data also publishes the same rows.

</details>

## 2. What does this do?

Why does `line_summary` declare `nullable_key=frozenset({"direction_id"})`?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Its both-directions rows have `direction_id` NULL (ADR-026), and a primary key can't contain NULLs. Publish builds a unique index with `NULLS NOT DISTINCT` instead, so the key is still enforced: only one both-directions row per line and window, where a plain unique index would treat every NULL as different.

</details>

## 3. What breaks if…

…the database URL were a command-line argument?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The password would be in shell history, in `ps` output that any user on the host can see, and in cron or Airflow logs that print the command. Hard rule 9 says never print or log credentials. The environment variable keeps it out of all three, and the deploy will fill it from SSM.

</details>

## 4. What breaks if…

…the integration test only checked that publish didn't raise?

**Your answer:**

>

<details>
<summary>Model answer</summary>

A source query that silently filters too much, such as a wrong window or a join that drops rows, would publish fewer rows and pass. The test compares every table's row count with its DuckDB source, and a second publish must leave each table's content digest identical. That catches both lost rows and non-idempotent loads.

</details>

## 5. How would you change it to…

…add `serving.trip_stop_time` for M3 commute matching?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Build a gold model in dbt first (schedule version × trip × stop sequence with local times), with grain tests. Then add one `ServingTable` entry: key (`schedule_version`, `trip_id`, `stop_sequence`), and an index on (`trip_id`, `stop_id`) as the API spec asks. The integration test picks it up automatically, because it iterates over `TABLES`. No migration is needed, because publish owns serving DDL (ADR-007).

</details>
