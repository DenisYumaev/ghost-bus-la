# Quiz 044 · Current cancellations

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

The newest trip-update fetch is 20:00 UTC. Trip B started at 19:30 and ends at 20:00, and was marked canceled at 19:45. Is it listed?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Yes. It was announced (`canceled_first_seen_at` is set), not reinstated, and its scheduled end (20:00) isn't past `as_of` (20:00): the condition is `sched_end_utc >= as_of`. Its advance notice is −900 s: the cancellation came 15 minutes after the scheduled start.

</details>

## 2. What does this do?

Why does `fct_current_cancellations` use the newest fetch instead of `now()`?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The table should say what the feed showed and when. With `now()`, a build that ran late would drop or keep trips based on the clock rather than the data, and two builds of the same data would disagree. With the newest fetch as `as_of`, the result is deterministic and the page can show "as of 4:52 PM".

</details>

## 3. What breaks if…

…publish refused empty loads for this table too?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Overnight, or on a good day, nothing is canceled, so the load is empty. Publish would refuse it every run and alert. Worse, the live table would keep yesterday evening's cancellations, so the page would show trips as canceled that aren't. `allow_empty` is set only on this table; a test pins that.

</details>

## 4. What breaks if…

…the endpoint filtered out lines not known to be Metro-operated, like the reliability numbers?

**Your answer:**

>

<details>
<summary>Model answer</summary>

A rider on a contracted line would not see an announced cancellation that the feed does carry. The reliability scope (SPEC section 2) is about which numbers we publish as headlines. This list just reports what the feed announced, so it isn't filtered (ADR-029 decision 3).

</details>

## 5. How would you change it to…

…switch to the detector's events in M3 without breaking clients?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Keep the response model (`as_of`, the cancellation list) and change only the repository: read `app.cancellation_event` rows not withdrawn and not yet departed, with `as_of` set to the detector's last processed snapshot time. The ETag source changes to the detector's cursor time. An ADR supersedes ADR-029 and retires `serving.cancellation_current`.

</details>
