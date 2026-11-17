# Quiz 021 · GTFS time and service-date math (`service_date.py`)

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

Walk through `to_utc(date(2026, 11, 13), parse_gtfs_time("25:10:00"))`. What does each step produce?

**Your answer:**

>

<details>
<summary>Model answer</summary>

1. `parse_gtfs_time` gives 25 × 3600 + 10 × 60 = 90,600 seconds. It's a count, not a clock reading, so 25 hours is fine.
2. `_reference` takes local noon on Nov 13 (12:00 PST, which is 20:00 UTC) and subtracts 12 real hours: 08:00 UTC on Nov 13, which is local midnight on a normal day.
3. Adding 90,600 s gives 09:10 UTC on Nov 14, which is 01:10 PST on Nov 14. The trip belongs to service date Nov 13 but runs on the calendar date Nov 14.

</details>

## 2. What does this do?

Why does `_reference` subtract the 12 hours *after* converting noon to UTC, instead of building "local noon minus 12 hours" in local time?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Python's arithmetic on an aware local datetime is wall-clock arithmetic: `datetime(…, 12, tzinfo=LA) - timedelta(hours=12)` gives 00:00 local, ignoring the clock change. On spring-forward day that's an hour off. The GTFS definition is 12 *elapsed* hours before noon, which is 23:00 the evening before. UTC has no gaps or repeats, so doing the subtraction there gives elapsed time. The property test `test_gtfs_seconds_are_elapsed_seconds` would catch the local-time version.

</details>

## 3. What breaks if…

…`to_utc` counted seconds from local midnight instead of from noon minus 12 hours?

**Your answer:**

>

<details>
<summary>Model answer</summary>

On the two clock-change days, every trip after 02:00 is placed an hour off. On spring-forward day, local midnight is PST but the day's trips run on PDT, so `08:00:00` lands at 09:00 PDT. Observed buses then look an hour early or late against the schedule, trip matching by time misses, and real trips are classified `missed`. It's wrong only two days a year, so it's easy to ship. This was checked by mutating the code: the midnight version fails the hand-checked clock-change cases and the daytime wall-clock property.

</details>

## 4. What breaks if…

…the parser compared GTFS times as text, for example to sort stop times?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Metro writes some hours without a leading zero (pipeline spec, section 4), so `"8:05:00" > "10:00:00"` as text. Stops would sort out of order, and a trip's first stop and start time would be wrong. That's why the spec says to parse into seconds and never compare times as text, and why `parse_gtfs_time` accepts one- or two-digit hours.

</details>

## 5. How would you change it to…

…do the same conversion inside dbt, on 2 million `stop_times` rows in DuckDB?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Use the same rule in SQL, not a Python call per row. Compute the reference once per service date: `timezone('America/Los_Angeles', service_date + INTERVAL 12 HOUR) - INTERVAL 12 HOUR` (DuckDB's `timezone(tz, timestamp)` interprets a naive timestamp as local time in `tz` and returns an instant). Then add `gtfs_seconds * INTERVAL 1 SECOND` per row, joining stop times to that small per-date table. Then test the SQL against this Python module on the same fixture dates, including the DST days, so the two implementations can't drift.

</details>
