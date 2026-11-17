# Quiz 023 · Building `dim_schedule_version` from bronze

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

`load_sightings` uses two sources. Which one decides that a ZIP exists, which one decides when it was first seen, and why not one source for both?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The **bronze listing** decides existence: only objects actually stored under `bronze/gtfs_static/` can be loaded. The **fetch log** decides timing: the earliest `written` line gives `first_seen_at`, which feeds `valid_from`. The listing's `LastModified` is the upload time, later than the fetch and on S3's clock. The fetch log alone can name ZIPs that aren't uploaded yet, or keys that don't exist at all (see question 2).

</details>

## 2. What does this do?

Why is a `duplicate` line's `object_key` never used?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Ingest builds that key from the day of the duplicate download (`dt=2026-11-16`), but the bytes were stored on the day they were first written (`dt=2026-11-15`). The real bucket has exactly this: two duplicate lines pointing at keys where nothing exists. A duplicate also can't be the first sighting, because a hash is always written before it can be a duplicate.

</details>

## 3. What breaks if…

…the loader guessed a first-seen time (say, midnight of the `dt=` day) for a ZIP with no `written` line, instead of stopping?

**Your answer:**

>

<details>
<summary>Model answer</summary>

`first_seen_at` sets `valid_from`, which decides which schedule every trip that day is matched against. Midnight UTC of `dt=` is the previous evening in Los Angeles, so the guess could start the new schedule a day early, and a service change would make a day of trips look missed. A loud `MissingSighting` costs one rerun after investigation. A silent wrong date corrupts every number built on it.

</details>

## 4. What breaks if…

…the S3 wrapper's `put` didn't refuse keys under `bronze/`?

**Your answer:**

>

<details>
<summary>Model answer</summary>

A bug, such as a wrong prefix constant, could overwrite raw data. The bucket policy denies deletes and unconditional overwrites on `bronze/*` (ADR-004), but that's one layer. The guard makes hard rule 1 fail in the pipeline's own code, in tests, before any request is sent. It's the same idea as ingest's conditional put: don't rely on one control for the one thing that can't be recovered.

</details>

## 5. How would you change it to…

…avoid reading every 22 MB ZIP on every run, once there are fifty versions?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Feed dates never change for a given hash (same bytes), so cache them. Write `feed_start_date`/`feed_end_date` per hash to a small Parquet file under `derived/` (or reuse the previous `dim_schedule_version`), and read the ZIP only for hashes not in it. Version resolution itself stays a full rebuild, because it's cheap and keeps the result idempotent. Only the expensive per-ZIP read is cached, keyed by content hash, so it can't go stale.

</details>
