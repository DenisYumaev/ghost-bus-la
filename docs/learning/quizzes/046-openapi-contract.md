# Quiz 046 · The OpenAPI contract

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

You rename `advance_notice_s` to `notice_s` in `schemas/cancellations.py` and run `make test`. What fails, and what do you do?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Two tests fail. `test_the_committed_document_matches_the_code` fails because the generated document no longer matches `services/api/openapi.json`. `test_every_success_response_has_an_example_that_validates` fails because the example still has `advance_notice_s` and lacks `notice_s`. You fix the example, run `make openapi`, and the diff to `openapi.json` shows the reviewer (and the web client) exactly what changed. A rename breaks clients, so it should be a deliberate decision, not a side effect.

</details>

## 2. What does this do?

Why does `problems.install` replace `app.openapi`?

**Your answer:**

>

<details>
<summary>Model answer</summary>

FastAPI declares every response body as `application/json`, but errors are served as `application/problem+json` (RFC 9457). The override moves error responses (4xx, 5xx) to the right media type once and caches the result in `app.openapi_schema`. Without it, a generated client would expect the wrong content type for errors.

</details>

## 3. What breaks if…

…an endpoint with query parameters didn't declare 422?

**Your answer:**

>

<details>
<summary>Model answer</summary>

FastAPI would add its own 422 with the `HTTPValidationError` schema (`detail: [{loc, msg, type}]`), which isn't what the app returns: the handler sends a problem document with `errors: [{field, message}]`. Clients generated from the document would parse validation errors wrongly. A test fails if `HTTPValidationError` appears in the components.

</details>

## 4. What breaks if…

…the examples used real-looking but invented numbers with no label?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Someone could quote "4.7% of 720 trips missed" from the docs as a finding, breaking hard rule 11 (honest numbers). The examples module says they are illustrative and never measured; their counts are only made internally consistent (missed = announced + unplanned, n_trips = scheduled − unknown).

</details>

## 5. How would you change it to…

…generate the web app's TypeScript client in CI and catch a client that's out of date?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Same pattern one step further: generate the client types from the committed `openapi.json` (for example with `openapi-typescript`, which needs an ADR as a new tool), commit them under `web/`, and fail CI when regenerating them produces a diff. Then `tsc` catches web code that uses a field the API no longer has.

</details>
