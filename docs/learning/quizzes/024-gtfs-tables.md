# Quiz 024 · Extracting schedule tables strictly

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

`stop_times.parquet` has both `arrival_time` and `arrival_s`. Why keep both?

**Your answer:**

>

<details>
<summary>Model answer</summary>

`arrival_time` is the text exactly as Metro published it (`29:45:00`, `8:55:30`), which is useful for display and for auditing a parse. `arrival_s` is seconds since noon minus 12 hours, an integer you can sort, subtract, and convert to UTC with `service_date.to_utc` or its SQL equivalent. Comparing the text form would order `8:55:30` after `10:00:00`.

</details>

## 2. What does this do?

Why does `typed_sql` check a regex before casting, when DuckDB already has `TRY_CAST`?

**Your answer:**

>

<details>
<summary>Model answer</summary>

`TRY_CAST` is lenient: on DuckDB 2.0, `'2.5'` becomes integer 3, `'1e2'` becomes 100, `'0x10'` becomes 16, and `'NaN'` is a valid DOUBLE. Those values would load silently and change meaning: a `stop_sequence` of 2.5 would collide with stop 3. The regex accepts only plain digits (or plain decimals in range for coordinates), so anything else becomes NULL, and `_check` refuses the version, naming an example.

</details>

## 3. What breaks if…

…the CSV reader used `auto_detect = true`, and one row of `calendar_dates.txt` were missing a field?

**Your answer:**

>

<details>
<summary>Model answer</summary>

DuckDB's sniffer decides the file isn't comma-separated and reads it as a single column, `service_id,date,exception_type`, with every row as one string. With all columns as text, nothing fails. The typed check would then find no `date` column at all, which the required-column check now catches. With auto-detection off and the options pinned, the short row raises `malformed CSV` right away. A data row starting with `#` would also be silently dropped as a comment under auto-detection.

</details>

## 4. What breaks if…

…the extractor were fixed later, but `_SUCCESS` didn't record an extractor version?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Every version already extracted keeps its old Parquet forever, because `_SUCCESS` means "done". You'd end up with versions extracted under different rules, maybe different columns, and nothing would tell you. With `extractor_version` in the marker, a newer extractor treats older markers as not done and rewrites them. `--force` redoes everything on demand.

</details>

## 5. How would you change it to…

…catch a `trip_id` with a stray trailing space, which would silently fail to match realtime trips?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Add an "identifier" kind for `trip_id`, `route_id`, `stop_id`, `service_id` and `block_id`. It refuses values whose trimmed form differs from the raw form, or that contain control characters, using the same `_check` scan. Run it against the real ZIP first: if Metro's data has such values, decide (and record) whether to refuse or to normalize, because normalizing changes the join key that realtime trip IDs must match.

</details>
