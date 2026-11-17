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

Grouping the fetch log only produces buckets in which something was fetched. During a partial outage, the missing buckets simply wouldn't exist, and a trip's share would come only from the healthy buckets that did, so it would be inflated toward 1.0 and the trip could be called `missed` instead of `unknown`. During a full outage the trip would have no buckets at all. Generating the full grid and left-joining the fetches makes an outage show up as unhealthy rows, and a window with no buckets at all is treated as `unknown` explicitly.

</details>

## 3. What breaks if…

…a trip seen only through trip updates (no positions) fell through the CASE with no branch for unknown coverage?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Its coverage is NULL, so `coverage >= 0.80` is NULL rather than true, and the `ran` branch doesn't fire. Without the second branch, the CASE would fall through to the feed-health check and then to `missed`. A trip we saw with a vehicle assigned would be counted as a missed trip, the headline metric, and the reconciliation identity would still hold, so no test would catch it. ADR-024's second branch, "observed, coverage below the threshold or unknown → partial", catches it explicitly, and a unit-test row pins it.

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
