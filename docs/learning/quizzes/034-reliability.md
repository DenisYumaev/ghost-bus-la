# Quiz 034 · `fct_reliability` and day types

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

A cell has 40 scheduled trips: 30 ran, 2 partial, 4 missed (1 announced), 4 unknown. What are `n_trips`, `missed_rate` and `unplanned_rate`?

**Your answer:**

>

<details>
<summary>Model answer</summary>

`n_trips` = 40 − 4 = 36. `missed_rate` = 4 / 36 ≈ 0.111. `unplanned_rate` = 3 / 36 ≈ 0.083. Unknown trips leave the denominator because we can't say whether they ran. Partial trips stay in it but never count as missed (pipeline spec section 8). If the cell had fewer than 10 service days, all three rates would be NULL and `suppressed` true.

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

The same data built on two different days would give different tables, so drill 3's "outputs identical" would fail. A late build would also shrink the window: if the pipeline stalled for three days, the `28d` window would contain only 25 days of data while claiming 28. Anchoring on the data keeps each window full and reproducible.

</details>

## 5. How would you change it to…

…also publish a rate for cells with 20 trips on 12 days, with a wider warning?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Don't lower the global threshold. Change the vars (`min_cell_trips`) only after checking how wide the bootstrap intervals are for small cells: if a 20-trip cell's 95% interval spans most of the scale, the rate tells a rider nothing. A better route is a coarser cell, such as a day type and 3-hour band, for thin lines. That keeps the threshold and gives a number someone can act on.

</details>
