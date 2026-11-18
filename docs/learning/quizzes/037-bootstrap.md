# Quiz 037 · Cluster bootstrap in dbt

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

A window has 3 service dates. Replicate 7 draws date indexes 2, 0, 2. What weights does `int_bootstrap_weights` store, and how does a cell's replicate missed rate come out if the dates had (trips, missed) = (10, 1), (10, 0), (10, 5)?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Weights: date 0 → 1, date 2 → 2, and date 1 gets no row. Replicate counts: trips 1 × 10 + 2 × 10 = 30, missed 1 × 1 + 2 × 5 = 11, so the rate is 11 / 30 ≈ 0.367. The real rate is 6 / 30 = 0.2. This replicate overweights the bad day. Across 2,000 such replicates, the spread of rates is the interval.

</details>

## 2. What does this do?

Why `hash(seed, window, r, k) mod n_dates` instead of `random()`?

**Your answer:**

>

<details>
<summary>Model answer</summary>

`random()` gives different draws on every build, so the same data would produce slightly different intervals each night. That breaks drill 3's "outputs identical" property and makes a changed number impossible to explain. The hash of fixed inputs is a reproducible pseudo-random draw: same seed and data, same intervals. It needs no stored random state.

</details>

## 3. What breaks if…

…you resampled trips instead of days?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The intervals would be far too narrow. Missed trips cluster: one day with an operator shortage can miss 20% of a line's trips, and the next day almost none. Resampling trips treats every trip as an independent coin flip and averages that clustering away. The interval would then claim a precision the data doesn't have. Resampling whole days keeps each day's shared cause together.

</details>

## 4. What breaks if…

…the percentiles used `quantile_cont` in one query, as the first version did?

**Your answer:**

>

<details>
<summary>Model answer</summary>

At 90 days it ran out of memory at a 3 GB limit. `quantile_cont` keeps every replicate value for every group in memory, about 75 million values, and DuckDB can't spill that aggregate to disk. Splitting the sums into their own table, then ranking (a sort, which spills) and interpolating with the same formula gave identical results, to 6 × 10⁻¹⁶, in about 90 seconds.

</details>

## 5. How would you change it to…

…stop the `all` window's cost growing forever?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Measure first: the cost is linear in days × cells × replicates, so log the step's runtime nightly. Then the options are:
- cap `all` at the most recent year and relabel it;
- use fewer replicates for `all` (1,000 still gives stable 95% bounds for most cells);
- compute `all` weekly instead of nightly, since it barely changes day to day.

Each is a var or a schedule change, recorded in an ADR with the measured runtime (ADR-027 "Would change if").

</details>
