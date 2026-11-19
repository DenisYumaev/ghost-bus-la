# Quiz 047 · The web scaffold

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

`vitest.config.ts` sets `TZ: "Asia/Tokyo"`, and the first time test asserts `getTimezoneOffset()` is −540. Why both?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Riders read Los Angeles times whatever zone their phone is in (web spec section 10). If tests ran in LA, code that formatted with the machine's zone would still pass. Running in Tokyo makes that bug fail. The offset assertion proves the setting took effect; without it, a config change could silently put the tests back in the machine's zone.

</details>

## 2. What does this do?

`percent(0.0001)` returns `"<0.1%"` and `percent(0.99999)` returns `">99.9%"`. Why not just round?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Rounding would show "0%" or "100%", which claims something false: some trips did miss, or not every trip ran. Honest numbers (hard rule 11; web spec section 1) mean a nonzero rate never reads as zero and an imperfect one never reads as perfect. A suppressed rate (null) is different again: "not enough data".

</details>

## 3. What breaks if…

…someone renames `missed_rate` to `miss_rate` in the API's Pydantic model and runs only the Python tests?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The Python contract test fails until `make openapi` updates `openapi.json`. `make openapi` also regenerates `web/lib/api/schema.ts`, so `tsc` fails wherever a page reads `missed_rate`. If they ran only the Python side of `make openapi`, CI's web job regenerates the types, sees a diff, and fails. Either way the rename can't merge with the web app still reading the old name.

</details>

## 4. What breaks if…

…the project upgraded to TypeScript 7 today?

**Your answer:**

>

<details>
<summary>Model answer</summary>

typescript-eslint supports TypeScript below 6.1, and openapi-typescript declares a peer of TypeScript 5. npm refuses the install (ERESOLVE), and forcing it risks lint rules and type generation breaking in ways that are hard to see. The upgrade waits until both support it.

</details>

## 5. How would you change it to…

…show "data as of 4:52 PM, may be out of date" on every page whose data is older than an hour, without repeating the check in each page?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Every response carries `data_as_of`, and `lib/time.ts` already has `isStale(dataAsOf, now)` with the 60-minute threshold from web spec section 4. Add one `StaleNotice` server component that takes `data_as_of` and renders nothing when fresh, and the notice (with `localTime`) when stale. Each page passes its response's `data_as_of`. A component test renders it in both states, with a fixed `now`.

</details>
