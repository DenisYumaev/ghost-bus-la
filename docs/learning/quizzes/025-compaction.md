# Quiz 025 · Compaction

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

Nov 14 has 2,880 vehicle-position objects in bronze and 2,880 rows in the compacted files. If two cuts had produced identical bytes, how many objects and how many rows would there be, and why?

**Your answer:**

>

<details>
<summary>Model answer</summary>

There would be 2,879 objects and 2,880 rows. Bronze is content-addressed, so identical bytes are stored once (the second put gets a 412 and counts as a duplicate). Compaction builds rows from the fetch log, one per `written` or `duplicate` fetch, and finds each row's bytes by hash. Both minutes stay observed, so the coverage that separates `unknown` from `missed` is preserved.

</details>

## 2. What does this do?

Why does compaction look up bytes in the previous day's objects too?

**Your answer:**

>

<details>
<summary>Model answer</summary>

A `duplicate` cut just after 00:00 UTC repeats the previous cut's bytes, which were stored under the previous day's `dt=` prefix. Looking only at today's prefix would report that fetch as a missing object. Today's objects win if a hash exists on both days.

</details>

## 3. What breaks if…

…each day were written as one file, as the spec first said?

**Your answer:**

>

<details>
<summary>Model answer</summary>

On DuckDB 2.0 the Parquet writer allocated one buffer the size of the whole BLOB column. For a day of trip updates (364 MB) that was 512 MiB, and the run failed at a 512 MB memory limit whatever the row-group size. Raising the limit works until the days get bigger, or until it runs on a 2 GB VM next to ingest. Two hundred snapshots per file bounds memory regardless of day size.

</details>

## 4. What breaks if…

…a rerun produced fewer part files than the first run, and stale parts weren't deleted?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Readers glob `dt=<day>/*.parquet`, so the old `part-2.parquet` would still be read, duplicating its rows, and the counts downstream would inflate. Rerunning would no longer give the same result (hard rule 2). The compactor lists the day's existing parts first and deletes the ones not rewritten. The delete refuses `bronze/`, like `put`.

</details>

## 5. How would you change it to…

…build the open day every 10 minutes for the live detector, as the spec plans?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Write to a separate `dt=<day>/_open/` prefix that readers of closed days ignore. Each run, compact only fetches newer than the last open part's newest `fetched_at` into a new part, instead of rewriting the day. When the day closes, the nightly run rewrites the day in full from the complete fetch log and deletes `_open/`. Open-day rows can't be final, because the fetch-log hour uploads only when the hour closes. The detector should read bronze or the spool for the last hour.

</details>
