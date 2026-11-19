# Quiz 045 · The SQL drill kit

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

`practice_connection()` runs `practice_data.sql` into a fresh `:memory:` DuckDB on every check.

**Your answer:**

>

<details>
<summary>Model answer</summary>

It rebuilds the synthetic tables from scratch for each check, so an attempt that drops or edits a table can't affect the next check, and since the generator uses only arithmetic (no random()), the reference answers are identical every time. The cost is a few hundred milliseconds per check, which is cheap for a drill.

</details>

## 2. What does this do?

`compare()` with `ordered=False`.

**Your answer:**

>

<details>
<summary>Model answer</summary>

It treats both results as multisets: it buckets rows by their non-numeric values, then pairs numbers within 0.001. Row order and column names are ignored, but duplicates, row count, column count and NULL-vs-0 all count. This tests what a query returns rather than how it was written, so any correct approach passes.

</details>

## 3. What breaks if…

…`cmd_start` kept the existing attempt file when you restarted a problem you'd already passed?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The old correct query would pass on the first check and log something like "0 min, 1 check" to `sql-log.md`. That's a fake time in the record behind the "medium in 20 minutes" goal, which breaks hard rule 11. So a restart backs up the old attempt to a `.bak` file and resets the attempt to the starter.

</details>

## 4. What breaks if…

…problem 02 used `WHERE stop_id NOT IN (SELECT stop_id FROM line_stops)`?

**Your answer:**

>

<details>
<summary>Model answer</summary>

line_stops has a NULL stop_id, so for every stop the NOT IN includes a comparison `stop_id <> NULL`, which is UNKNOWN. That makes the whole predicate UNKNOWN, never TRUE, and the query returns no rows. NOT EXISTS (or a LEFT JOIN … WHERE ls.stop_id IS NULL) ignores the NULL row.

</details>

## 5. How would you change it to…

…let drills run against the real warehouse instead of synthetic data?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Point `practice_connection()` at `data/ghostbus.duckdb` opened read-only, and rewrite the problems against the real table names. But the answers would change with every nightly build, so you couldn't store fixed expected results: the checker would have to run the reference query live each time (it already does), and tests would need a pinned fixture warehouse. The real data also has no planted traps, which is why the drills use synthetic data and the README sends free practice to the real one.

</details>
