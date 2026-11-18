# Quiz 036 · System summary and weekly trend

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

`cast(date_trunc('week', service_date) as date)` for service date Sunday 2027-01-03.

**Your answer:**

>

<details>
<summary>Model answer</summary>

It returns Monday 2026-12-28. DuckDB's weeks start on Monday (ISO), so that Sunday is the last day of the week starting Dec 28, and Monday Jan 4 starts the next week. That's why `fct_line_trend`'s first and last weeks can be partial, and why `n_service_days` is published next to each week.

</details>

## 2. What does this do?

Why does `fct_system_summary` read `int_trip_cells` rather than `fct_trip_outcomes`?

**Your answer:**

>

<details>
<summary>Model answer</summary>

So it counts exactly the trips the reliability grid counts: the same Metro-operated scope, the same day types, the same windows. If the summary read the outcomes directly, a later change to the scope (the contracted-lines filter) could land in one place and not the other. The home page would then disagree with the line pages. A dbt test checks that the totals match.

</details>

## 3. What breaks if…

…the trend used the reliability day minimums (10 weekday days)?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Every week would be suppressed forever, because a week has at most 7 service days, or 5 weekdays. The trend chart would never show a point. But no day floor at all would let a week with a single day of data, such as the newest or the first, plot one bad day as a weekly spike. ADR-026 sets 4 days, a majority of the week, plus the 30-trip floor, and `n_service_days` lets the chart mark weeks with 4 to 6 days as partial.

</details>

## 4. What breaks if…

…the summary's rate were the average of the line rates?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Small lines would weigh as much as busy ones. A line with 40 trips and a 20% missed rate would pull the headline as hard as one with 4,000 trips. The system rate is total missed over total trips (section 8), which weights each trip equally: that's what "share of scheduled trips that never ran" means. Averaging rates also can't handle suppressed lines, which have no rate.

</details>

## 5. How would you change it to…

…show the summary for rush hours only (6–9 AM weekdays)?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Add a dimension, not a new pipeline: filter `int_trip_cells` on `day_type = 'weekday' and hour_local between 6 and 8`, and group by window as now. As a table, it's a second row set keyed by a `scope` column ('all', 'weekday_peak'). Because it reads the same trip cells, the peak numbers stay consistent with the grid's 6, 7 and 8 AM weekday cells. That's an idea for `docs/ideas.md`, not M2 scope.

</details>
