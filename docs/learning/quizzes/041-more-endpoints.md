# Quiz 041 · Line list, detail, stops, system summary, feed health

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

`GET /v1/lines` adds `{"_today": "2026-11-18"}` to its ETag key. Why?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The list shows the schedule version in force today. At midnight on a service change, the version can change with no publish at all, so the list's lines and names change while every `data_as_of` stays the same. Putting today's date in the tag makes the tag change at midnight, and a client can't keep yesterday's list through a 304.

</details>

## 2. What does this do?

The line page's headline for line 720 comes from `line_summary` where `direction_id IS NULL`. What is that row?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Both directions pooled: total missed over total trips across directions 0 and 1 (ADR-026). It's not the average of the two direction rates, which would weight a quiet direction as much as a busy one. dbt builds it with grouping sets, and a test checks it equals the sum of the direction rows.

</details>

## 3. What breaks if…

…feed health counted back from `now()` instead of the newest bucket?

**Your answer:**

>

<details>
<summary>Model answer</summary>

If the pipeline stalled for a day, the status page would come back empty, which says nothing about why. Counting back from the newest bucket shows the last day the data has. The staleness itself is reported by `/readyz` and by `data_as_of`, where it belongs.

</details>

## 4. What breaks if…

…each endpoint built its own ETag?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Each one would need to remember every table its body reads. Forget one, such as the line tables behind a headsign, and a client keeps a stale body through 304s. One helper that takes the table list makes that list explicit and reviewable, and the tests check every endpoint revalidates.

</details>

## 5. How would you change it to…

…add `?direction_id=` filtering to `/v1/lines/{line}/stops` for both directions at once?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Make `direction_id` optional. Without it, return a list of direction blocks (`direction_id`, `headsign`, stops), each from the same repository query called once per direction, or one query ordered by `direction_id, stop_order` grouped in Python. The ETag needs nothing new: the query string is already part of the key.

</details>
