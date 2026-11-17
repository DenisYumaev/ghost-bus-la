# Quiz 031 · Feed health and trip outcomes v1

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

A trip wasn't observed, and its window spans 30 five-minute buckets. Trip updates were unhealthy in 4 of them, and vehicle positions in 0. What's the outcome?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The feed-healthy share counts buckets in which *both* feeds were healthy: 26 of 30, about 0.87. That's under the 0.90 threshold, so rule 3 applies and the outcome is `unknown`, not `missed`. With feeds partly down, a missing trip could be a data gap, and the project never calls a gap a missed trip.

</details>

## 2. What does this do?

Why does `int_feed_health_5min` generate every bucket of the synced days, instead of grouping the fetch log?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Grouping the fetch log only produces buckets in which something was fetched. During a full outage there are no fetch-log lines, so there would be no rows. The outage would be invisible, and every trip in it would get a share of 1.0 from the buckets that did exist. Generating the full grid and left-joining the fetches makes an outage show up as unhealthy rows.

</details>

## 3. What breaks if…

…a trip seen only through trip updates (no positions) fell through the CASE with no branch for unknown coverage?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Its coverage is NULL, so `coverage >= 0.80` is NULL rather than true, and the `ran` branch doesn't fire. Rules 3 and 5 test "not observed", which is false, so the trip would get no outcome. That breaks the reconciliation identity (scheduled = sum of outcomes), which a dbt test enforces. ADR-024's second branch, "observed, coverage below the threshold or unknown → partial", catches it explicitly.

</details>

## 4. What breaks if…

…M1's `missed` rate were quoted on the site?

**Your answer:**

>

<details>
<summary>Model answer</summary>

It would overstate missed service. Rule 4 (`likely_untracked`: a trip not observed, but its block neighbours ran with the same vehicle, so the bus probably ran without reporting) isn't built until M4. In M1 those trips fall to `missed`. The numbers also haven't been checked against Metro's own report (M5). Hard rule 11 says every published number must be defensible, and these aren't yet.

</details>

## 5. How would you change it to…

…tune the 0.80 coverage threshold responsibly?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Hand-check a sample of trips near the threshold, say coverage 0.6–0.95, against the raw positions: did the bus really complete the route? Then pick the value that best separates complete from incomplete, and run the sensitivity in one command (`dbt build --vars '{min_stop_coverage: 0.75}'`) to see how much the headline moves. Freeze the choice in an ADR with the evidence, as spec section 8 asks.

</details>
