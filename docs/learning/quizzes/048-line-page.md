# Quiz 048 · The line page

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

The cancellations API answers 503 while the line detail and both reliability grids load fine. What does the rider see?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The full line page, with "Current cancellations are unavailable right now" in that section. `orNull` turns a 404 or 503 `ApiError` into `null` for secondary sections. An empty list would look like a quiet day (ADR-029), so the page says the data is missing instead. A 503 for the line detail itself is different: it throws to `app/error.tsx`, never to "line not found". A network failure (not an `ApiError`) also throws.

</details>

## 2. What does this do?

Why does the heatmap use a `<details>` table instead of a "view as table" button?

**Your answer:**

>

<details>
<summary>Model answer</summary>

A button needs client JavaScript (state) to toggle; `<details>` is native HTML, works before any script loads, and is keyboard and screen-reader accessible. The page stays a pure server component, and color is never the only signal: each SVG cell has a text label, and the table repeats every number.

</details>

## 3. What breaks if…

…`beforeEach(() => apiGet.mockReset())` is written as an arrow with an expression body?

**Your answer:**

>

<details>
<summary>Model answer</summary>

`mockReset()` returns the mock itself, so the arrow returns a function. Vitest treats a function returned from `beforeEach` as that hook's teardown and calls it after each test, with no arguments. The mock then throws "unexpected undefined" and every test fails for a reason unrelated to the code. A block body (`{ apiGet.mockReset(); }`) returns nothing.

</details>

## 4. What breaks if…

…a suppressed cell were drawn with the lightest color instead of a hatch?

**Your answer:**

>

<details>
<summary>Model answer</summary>

It would read as "under 2% never ran": a good number the data can't support. Honest numbers (web spec section 1) require "not enough data" for suppressed cells, never a value. The test checks the suppressed cell's fill is the hatch pattern and its label says "not enough data (12 trips)".

</details>

## 5. How would you change it to…

…build every line's page ahead of time instead of on first request?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Return the slugs from `generateStaticParams` by calling `GET /v1/lines` at build time. The catch: the build then needs a reachable, published API (Vercel builds would call the VM), and a failed fetch fails the deploy. Returning `[]` keeps the build independent of the API, and ISR caches each page once a rider visits it.

</details>
