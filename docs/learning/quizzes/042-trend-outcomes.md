# Quiz 042 · Trend and trip outcomes

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

`WHERE (sched_start_utc, trip_id) > (:after_start, :after_trip) ORDER BY sched_start_utc, trip_id LIMIT 51`

**Your answer:**

>

<details>
<summary>Model answer</summary>

It is keyset pagination. A row-value comparison returns the rows that sort after the last row of the previous page: a later start, or the same start with a later trip ID. With an index on (line, service_date, sched_start_utc, trip_id) it's a range scan from that point. It asks for 51 so the API knows whether there is a next page (50 shown, one more means "more") without a separate count.

</details>

## 2. What does this do?

Why is the cursor base64 of the key rather than the key itself?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Opacity. Clients pass back what they were given and don't build cursors themselves, so the sort key can change later, for example by adding a column, without breaking anyone. It is also URL-safe. A cursor that doesn't decode to this API's shape is a 400, not a 500.

</details>

## 3. What breaks if…

…pagination used `OFFSET 50` for page 2, and a publish landed between the two requests?

**Your answer:**

>

<details>
<summary>Model answer</summary>

If the new publish added a trip early in the day, everything shifts by one: page 2 repeats the last trip of page 1. If it removed one, page 2 skips a trip. Keyset pagination continues after the last key seen, so it neither repeats nor skips. Offsets also get slower as they grow, because the database still reads and discards the skipped rows.

</details>

## 4. What breaks if…

…the trend returned only the weeks that have data?

**Your answer:**

>

<details>
<summary>Model answer</summary>

A line that didn't run for two weeks (a detour, a seasonal service) would plot its neighbouring weeks next to each other, and the chart would hide the gap. The endpoint generates every Monday in the range and left-joins the data, so missing weeks come back as empty points the chart can show as gaps.

</details>

## 5. How would you change it to…

…let the trip list be filtered by outcome (only missed trips)?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Add an optional `outcome` query parameter and `AND (CAST(:outcome AS text) IS NULL OR outcome = :outcome)` in the repository. The keyset cursor still works, because the filter doesn't change the sort key, and the query string is already part of the ETag key. At a few hundred rows per line and date the extra filter costs nothing; if it ever did, add `outcome` to the index after `service_date`.

</details>
