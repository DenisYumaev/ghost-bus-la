# Quiz 030 · Crosswalk and observations

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

When does `int_trip_observations` say a trip was observed running?

**Your answer:**

>

<details>
<summary>Model answer</summary>

When, inside the observation window (scheduled start −30 minutes to scheduled end +60 minutes), at least one vehicle position matched the trip exactly on (trip_id, service_date), or at least one of the fetch's *chosen* trip reports was SCHEDULED and carried a vehicle ID. A CANCELED report is not an observation. A SCHEDULED report without a vehicle is only a prediction.

</details>

## 2. What does this do?

Why does `max_stop_sequence` come from vehicle positions and not from trip updates?

**Your answer:**

>

<details>
<summary>Model answer</summary>

A trip update predicts arrival at the stops *still ahead*, so its stop sequences run to the end of the route even before the bus leaves. Their maximum would put every trip near its last stop, and coverage would be about 1.0 for everything. A vehicle position's `current_stop_sequence` is where the bus actually is (or is heading next), so its maximum over the window shows real progress.

</details>

## 3. What breaks if…

…observations counted every report in `stg_trip_reports`, not only `is_chosen`?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The non-chosen reports include stale SCHEDULED reports that still carry a vehicle next to a newer cancellation. That's exactly the pattern found in 227 snapshots. Counting them would mark canceled trips as observed running, which turns announced cancellations into "announced but ran" and hides them from the missed counts.

</details>

## 4. What breaks if…

…outcomes in M1 used only "observed running" to decide `ran`, with no coverage rule?

**Your answer:**

>

<details>
<summary>Model answer</summary>

On Nov 15, 121 trips were both observed and canceled. Most were mid-trip cancellations: the bus ran part of the route (median 0.21 of it after the start), stopped reporting, and the trip was marked canceled. Twelve only waited at the first stop before departure. Without the coverage threshold (rule 2, `partial` below 0.80), all of them would count as `ran`, which overstates service. `partial` is reported separately and never counted as missed (spec section 8).

</details>

## 5. How would you change it to…

…catch a schedule-version loading problem from the crosswalk?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Watch the in-scope match rate per service date: the share of realtime trip keys that match the expanded schedule exactly. Metro's trip IDs embed a service-change tag, so if a new version wasn't loaded, realtime IDs stop matching and the rate drops sharply. The `trip_match_rate_is_healthy` test warns under 95%. Nov 15 was 9,532 of 9,532. Keys from dates outside the synced range are excluded (`in_scope`), so they don't look like failures.

</details>
