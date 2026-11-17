# Quiz 034 · `fct_reliability` and day types

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

A cell has 40 scheduled trips: 30 ran, 2 partial, 4 missed (1 announced), 4 unknown. What are `n_trips`, `missed_rate` and `unplanned_rate`?

**Your answer:**

>

<details>
<summary>Model answer</summary>

`n_trips` = 40 − 4 = 36. `missed_rate` = 4 / 36 ≈ 0.111. `unplanned_rate` = 3 / 36 ≈ 0.083. Unknown trips leave the denominator because we can't say whether they ran. Partial trips stay in it but never count as missed (pipeline spec section 8). If the cell had too few service days (10 for a weekday cell, 4 for a weekend cell; ADR-025), all three rates would be NULL and `suppressed` true.

</details>

## 2. What does this do?

A trip of service date Saturday Nov 21 is scheduled at 25:30. Which cell is it in?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Day type `saturday` (from its service date), hour 1. The hour is the local clock hour of the scheduled start, which is 01:30 on Sunday morning. But the trip belongs to Saturday's service, so it is counted with Saturday's cells. A rider sees it in the Saturday row at 1 AM, which is how the printed schedule lists it.

</details>

## 3. What breaks if…

…day type came from the calendar day instead of the schedule?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Thanksgiving (Thursday Nov 26, 2026) runs Sunday service: the schedule adds the `…_Sunday` service IDs that day. Counted as a weekday, its trips would land in weekday cells. Sunday operations would be mixed into weekday hours, and the weekday 28-day rates would shift for a reason no rider would guess.

</details>

## 4. What breaks if…

…the windows ended at `current_date` instead of the last service date with outcomes?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The same data built on two different days would give different tables, so drill 3's "outputs identical" would fail. A late build would also shrink the window: if the pipeline stalled for three days, the `28d` window would contain only 25 days of data while claiming 28. Anchoring on the data makes the window reproducible and stops it shrinking as the clock moves. It doesn't make it full: early on, or after a gap, there are fewer days, which is why each cell also reports `first_data_date` and `n_service_days`.

</details>

## 5. How would you change it to…

…also publish rates for weekend cells in the 28-day window, which can never hold 10 Saturdays?

**Your answer:**

>

<details>
<summary>Model answer</summary>

That is what ADR-025 did: the day minimum depends on the day type (10 for weekdays, 4 for weekends, all the Saturdays a 28-day window can hold), and the 30-trip floor stays. Fewer days means a less certain rate, so it goes with the bootstrap interval, which shows the uncertainty instead of hiding the number. If the intervals turn out too wide to tell lines apart, raise the weekend minimum or default weekend views to `90d`. The alternative, coarser weekend cells, still needs the day minimum, so it doesn't fix the 28-day window.

</details>
