# Quiz 026 · Decoding realtime frames

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

Nov 14's trip-update feed had 4,610,461 frames but `trip_update` has 42,417,214 rows. Where do the extra rows come from, and how is a cancellation represented?

**Your answer:**

>

<details>
<summary>Model answer</summary>

A trip update frame carries a list of stop-time updates (predicted arrival and departure per upcoming stop), and decode writes one row per stop-time update, so a trip with 20 upcoming stops gives 20 rows. A canceled trip carries no stop-time updates, so it gets exactly one row with the trip fields filled in, `trip_schedule_relationship = 'CANCELED'`, and null stop fields. There's no separate cancellation table (spec section 3).

</details>

## 2. What does this do?

Why does `frames._typed` reject `"directionId": true` and `"directionId": 0.5`, when Python would happily treat `True` as 1?

**Your answer:**

>

<details>
<summary>Model answer</summary>

In Python, `bool` is a subclass of `int`, so `isinstance(True, int)` is True. Without the explicit exclusion, `true` would load as direction 1. `0.5` isn't an integer at all. Either one means the producer sent something unexpected, and silently coercing it would put a trip in the wrong direction. So the frame is quarantined with `bad:tripUpdate.trip.directionId` and its exact bytes, and someone can look.

</details>

## 3. What breaks if…

…the schema-drift alert fired on any new fingerprint, as the plan first said?

**Your answer:**

>

<details>
<summary>Model answer</summary>

It would fire every night. On Nov 14, 34 trip-update snapshots between 01:03 and 02:46 Los Angeles had a different fingerprint, only because an optional field was absent when few trips run. An alert that fires nightly gets ignored, and then a real format change is missed. Drift is therefore defined as a field path or type not in the approved set. Absences don't count.

</details>

## 4. What breaks if…

…bad frames were dropped instead of quarantined?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Every dropped trip-update frame is a trip with no observation in that snapshot. Enough of them and a running trip looks missed, or a cancellation is never seen. Worse, nobody would know, because the count would just be lower. The quarantine keeps the reason and the exact bytes, the marker counts them by reason, and the spec rule "decode never drops a record" stays checkable. Nov 14 had 0, which is itself a useful fact.

</details>

## 5. How would you change it to…

…make trip-update decoding (322 s, 42 million rows for one day) fast enough to run every 10 minutes for the open day?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Decode only what's new: the open day's compaction adds parts incrementally, so decode just the new parts (one part is 200 snapshots, about 30 s of work). The hot path doesn't need every stop prediction anyway: the detector needs cancellations and trip starts. A slimmer `trip_status` table (one row per trip per snapshot, no stop-time updates) is about a tenth of the rows. Measure before changing anything. Parallelising across parts with processes is the other easy lever, since each part is independent.

</details>
