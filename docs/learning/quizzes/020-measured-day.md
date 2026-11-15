# Quiz 020 · PR #23 · The measured day and accepting ADR-021

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

Where do the measured-day numbers come from, and why from there rather than from listing the S3 objects?

**Your answer:**

>

<details>
<summary>Model answer</summary>

From the **fetch log**: `scripts/measure_day.py` reads `bronze/_fetch_log/dt=2026-11-14/`, takes the union of lines, and sums the `fetch` events. Listing S3 objects would show only what was stored. The fetch log also records what was **attempted**, including the four empty `network_error` minutes that stored nothing (reason `no_messages`), and the uncompressed size (`bytes`) next to the stored size (`bytes_gz`). The "99% of scheduled polls attempted" criterion can only be checked from the log.

</details>

## 2. What does this do?

Why does `summarize` take a `set` of lines?

**Your answer:**

>

<details>
<summary>Model answer</summary>

A restart in the middle of an hour uploads that hour's fetch-log file twice under different content-addressed keys (ADR-004). Both files contain the lines written before the restart. Taking the union of lines as a set counts each event once. A list would double-count every attempt in that hour. `test_duplicate_lines_from_a_reuploaded_hour_count_once` covers it.

</details>

## 3. What breaks if…

…someone quotes "ingest stores 0.49 GB a day" in the README a year from now without rerunning the query?

**Your answer:**

>

<details>
<summary>Model answer</summary>

It may no longer be true. Fleet size, service levels, or message shapes change, and so does the volume. Hard rule 11 says every number traces to a query or a committed report, so a quoted number must name its date and source ("measured on 2026-11-14") or be refreshed by rerunning `scripts/measure_day.py`. The report is dated for exactly this reason.

</details>

## 4. What breaks if…

…the cadences had been cut to vehicle positions every 120 s to save money?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The saving is tiny: storage costs about $0.35 a month more each month, and positions are about a quarter of it. The cost: gaps between position samples grow to 2 minutes, so a bus's arrival at each stop is known less precisely. Stop-level reliability (M5) and inferring which vehicle runs which block (M4) both depend on that, and the history can't be recovered later. (The likely-missing detector would still work: its signal is "no vehicle seen by start + 10 minutes", which 120 s sampling still catches.) The measurement showed no reason to cut, so the decision kept 30 s and 60 s.

</details>

## 5. How would you change it to…

…track the daily volume automatically, so a sudden jump (for example Metro adding fields) gets noticed?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Run the same aggregation daily, from the pipeline (cron now, Airflow from M4), over the previous UTC day. Store one row per feed per day (`attempted`, outcomes, raw and gzipped bytes) in a small table, and alert when a value moves outside a band, say ±30% of the trailing 7-day median, or captured minutes fall below the capture SLO (99.5% of minutes per feed per month, ADR-003), which belongs in M5's SLO work. (The 99% of polls attempted figure is M0's one-time acceptance test, not the SLO.) The schema-fingerprint check (pipeline spec, section 10) catches the shape change directly.

</details>
