# Quiz 029 · Schedule expansion

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

How does `int_schedule_expanded` decide whether service `WK` runs on Monday 2026-11-16?

**Your answer:**

>

<details>
<summary>Model answer</summary>

It takes the schedule version in force for that date (`int_service_dates`). `WK` runs if its `calendar` row covers the date (`start_date`–`end_date`) and has `monday = 1`, or if `calendar_dates` adds it that day (exception 1). It does not run if `calendar_dates` removes it (exception 2). In SQL: `weekly UNION added EXCEPT removed`, so a removal always wins. Then every trip of each active service is joined to its stop times for the first and last stop.

</details>

## 2. What does this do?

Why does `gtfs_to_utc` add `interval 12 hour` to the date and then subtract it again?

**Your answer:**

>

<details>
<summary>Model answer</summary>

It isn't a no-op, because the two steps happen on different clocks. `timezone('America/Los_Angeles', date + 12h)` turns *local noon* into an instant. Subtracting 12 hours from that instant is elapsed-time arithmetic. That's the GTFS reference "noon minus 12 hours", which is 23:00 the evening before on spring-forward day and 01:00 on fall-back day. Anchoring at local midnight instead fails 10 of the 16 hand-checked cases. That was checked by mutating the macro.

</details>

## 3. What breaks if…

…the SQL and Python versions of the time rule were tested separately, each against its own examples?

**Your answer:**

>

<details>
<summary>Model answer</summary>

They could each pass their own tests and still disagree, for example on owl trips the evening before a clock change. The detector (Python) and the outcomes (SQL) would then place the same trip an hour apart. Both are therefore tested against one file, `tests/fixtures/dbt_seeds/gtfs_time_cases.csv`: Python reads it in pytest, and dbt loads it as a seed for `gtfs_to_utc_matches_hand_checked_cases`.

</details>

## 4. What breaks if…

…`int_service_dates` covered every UTC day that sync copies, instead of only the requested range in `_sync.json`?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Sync also copies the UTC day before and the day after the range, but those service dates are only partly covered. The day after has only its morning, for example, so evening trips would have no observations and would look missed. Scoping to `_sync.json`'s start..end keeps expansion to dates the local copy covers completely.

</details>

## 5. How would you check the expansion is right on real data, independently of the SQL?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Re-derive one day from the raw GTFS with different code. Read `calendar.txt`, `calendar_dates.txt`, `trips.txt` and `routes.txt` from the ZIP in plain Python, apply the weekday, date-range and exception rules, and count the trips. (`scripts/check_schedule_expansion.py` does this.) For Sunday 2026-11-15 both gave 9,534 trips, 12 active services, and 110 trips on line 754. Two implementations agreeing on real data is much stronger evidence than either one's own tests.

</details>
