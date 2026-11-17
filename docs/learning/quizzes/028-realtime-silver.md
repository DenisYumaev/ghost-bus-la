# Quiz 028 · Realtime silver: reports, updates, cancellations

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

Why is there a `stg_trip_reports` table between the decoded trip updates and `stg_cancellations`?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Decode writes one row per stop-time update, which is about 40 million rows a day. Most consumers need one row per trip *report*: which trip, in which fetch, from which entity, with what relationship, vehicle and timestamp. That's about 5 million rows a day. `stg_trip_reports` collapses the stop rows back into reports, marks the newest report per trip-fetch as `is_chosen`, and is a table, so `stg_cancellations` and the coming observations don't re-run windows over stop rows on every build.

</details>

## 2. What does this do?

In one snapshot, trip T has a report with vehicle 5898 and timestamp 09:59:40, and another with no vehicle, marked CANCELED, timestamp 10:00:10. Which wins, and why not the one with the vehicle?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The cancellation wins, because it's the newest by Metro's own timestamp. On Nov 14–16, 266 snapshots had two disagreeing reports of a trip. In 227 of them the newer one was a cancellation without a vehicle, next to an older report that still carried the bus assignment. "Prefer the vehicle" would have hidden 227 real cancellations. The vehicle only breaks ties on equal timestamps.

</details>

## 3. What breaks if…

…`stg_cancellations` ordered *every* report (chosen or not) by Metro's timestamp, instead of using one chosen state per fetch?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Metro re-stamps a lingering cancellation on every fetch (1,107 of 1,111 canceled entities changed timestamp), and some trips have two live entities at once, a cancellation and an old vehicle report, both refreshing. Ordering all their reports by timestamp interleaves the two, so a cancellation looks retracted and re-issued. On Nov 15 that invented 5 of 11 "later final episodes", shortening the measured advance notice. Taking one state per fetch, from the report `stg_trip_reports` chose, gives one consistent sequence. It's the same choice `stg_trip_updates` uses, so the models agree.

</details>

## 4. What breaks if…

…advance notice for a trip canceled at 06:00, reinstated at 07:00 and canceled again at 08:00 were measured from 06:00?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Notice would be overstated by two hours. Between 07:00 and 08:00 riders were told the trip would run, so the warning they could act on started at 08:00. Advance notice is the M1 product gate: if the median is under 10 minutes, announced-cancellation alerts become a secondary feature. Overstated notice could pass that gate wrongly. `first_seen_at` is therefore the first fetch of the final episode, and `first_ever_canceled_at` is kept for reference.

</details>

## 5. How would you change it to…

…apply the alerts spec's rule that a cancellation is withdrawn only while the trip's scheduled start is still ahead?

**Your answer:**

>

<details>
<summary>Model answer</summary>

That rule needs the schedule, which silver doesn't join. In `int_trip_observations`, join `stg_cancellations` to the expanded schedule for the version in force (`sched_start_utc`) and compute `rt_canceled = not (reinstated_at < sched_start_utc)`: a reinstatement counts only if it came before the scheduled start. On Nov 15, 4 of 121 reinstatements came after the start. Under a naive rule those trips would be classified "not announced", which inflates the unplanned-missed headline number.

</details>
