# Quiz 032 · Drill 3: run the same day twice

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

`md5(string_agg(md5(CAST(t AS VARCHAR)), '' ORDER BY ...))` over a table. Why hash each row first and sort, instead of hashing the table as DuckDB returns it?

**Your answer:**

>

<details>
<summary>Model answer</summary>

DuckDB doesn't promise row order without an ORDER BY, and the dbt profile sets `preserve_insertion_order = false`, so two identical builds can return rows in different orders. Hashing each row and sorting the hashes gives a canonical order for any table without knowing its key. Duplicates still count, because each copy adds its own hash to the list.

</details>

## 2. What does this do?

Why does re-running `make compact` for a day not create duplicate data, even though it writes a whole new set of parts?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Each run writes under its own `run=<id>/` prefix and then a `_SUCCESS` marker listing exactly its parts. Readers follow the marker, never a glob, so they see one complete run. The old run is deleted only after the new marker is in place. A crash halfway leaves the old marker pointing at the old, complete parts.

</details>

## 3. What breaks if…

…a model used `now()` or `current_date` (for example, to compute "trips in the last 7 days")?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The same input would give different output depending on when it was built, so this drill would fail and backfills couldn't be reproduced. No model reads the clock: date ranges come from the synced range (`src_sync_range`), so the inputs alone determine the tables. The one deliberate exception is a warning test, `schedule_calendar_runs_out_soon`, which compares against `current_date` because "is the schedule about to expire?" really is a question about today. It produces a warning and no table rows.

</details>

## 4. What breaks if…

…the drill compared only row counts?

**Your answer:**

>

<details>
<summary>Model answer</summary>

It would miss any non-determinism that keeps counts the same: a tie-break that picks a different "chosen" report on each run (the `is_chosen` ordering ends with `entity_key` for exactly this reason), a different vehicle, or a shifted timestamp. Outcomes could flip from `ran` to `partial` while every count stayed put.

</details>

## 5. How would you change it to…

…run this check automatically, without AWS?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Use the offline end-to-end test world (`pipeline/decode/tests/world.py`): build it, compact and decode twice into a fake bucket, run dbt after each, and assert the fingerprints match. That puts the same property in CI on every PR. The real-data drill stays as the check at scale.

</details>
