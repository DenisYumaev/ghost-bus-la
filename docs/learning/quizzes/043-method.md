# Quiz 043 · The method endpoint

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

`('min_stop_coverage', '{{ var("min_stop_coverage") }}', ...)` in a dbt model.

**Your answer:**

>

<details>
<summary>Model answer</summary>

dbt renders the var's value into the SQL at compile time, so the row holds the value this build used, such as '0.8'. A sensitivity run with `--vars '{min_stop_coverage: 0.75}'` builds both the numbers and this row with 0.75, so the method page always matches the rates beside it.

</details>

## 2. What does this do?

Why are the outcome definitions in API code but the thresholds in a table?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The definitions change only with a decision: an ADR changes the decision table, and the code changes in the same PR. The thresholds are parameters that can differ between builds (a sensitivity run, a tuning ADR), so they must come from the build that made the numbers.

</details>

## 3. What breaks if…

…the method page hard-coded "80% of stops"?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The day the threshold is tuned to 0.75 in a frozen ADR, the rates change and the page still says 80%. A reader checking the method against the numbers would find them inconsistent, which breaks hard rule 11. Rendering from the build removes that failure.

</details>

## 4. What breaks if…

…the notes said "trips Metro hid"?

**Your answer:**

>

<details>
<summary>Model answer</summary>

It breaks SPEC section 2.7 and hard rule 12. What the `CANCELED` flag covers isn't documented, so the project claims nothing about why a trip wasn't marked. The copy says "announced cancellation" and "unplanned missed trip", and always "not affiliated with LA Metro".

</details>

## 5. How would you change it to…

…show when each threshold last changed?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Add a `since` column: the ADR that set the value already appears in `decision`, so record its date with it, or compute it from history by keeping `ops.publish_run`-style rows of each published value and showing the first date the current value appeared. The first is simpler and auditable, because every change goes through an ADR.

</details>
