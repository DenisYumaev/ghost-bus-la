# Quiz 049 · Home, lines, method and status pages

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

`byReliability` sorts lines least reliable first. Where does a line with a suppressed summary go, and why?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Last, in line-number order. A suppressed summary has no rate we may show; sorting it as 0 would rank it "most reliable", which the data can't support (honest numbers). The test includes a summary marked suppressed that still carries a rate, to prove the flag wins.

</details>

## 2. What does this do?

Why does `healthByDay` group by a `Intl.DateTimeFormat("en-CA", { timeZone: "America/Los_Angeles" })` key instead of `bucket_start.slice(0, 10)`?

**Your answer:**

>

<details>
<summary>Model answer</summary>

`bucket_start` is UTC. Slicing would put 4 PM to midnight Pacific time into the next day. The en-CA locale formats as `YYYY-MM-DD`, so the key is the Los Angeles date and sorts as a string. The test puts 07:55 UTC on Dec 2 into Dec 1.

</details>

## 3. What breaks if…

…the home page kept `export const revalidate = 60` and no `dynamic` setting?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Next prerenders it during `next build`, which calls the API. In CI (no API) the build fails with "GHOSTBUS_API_URL is not set"; on Vercel the deploy would fail whenever the VM is down or unpublished. `force-dynamic` renders at request time; the API response is still cached for 60 s by the fetch cache.

</details>

## 4. What breaks if…

…the home page showed the system summary's missed rate now?

**Your answer:**

>

<details>
<summary>Model answer</summary>

It would publish a headline number the API itself marks internal until M5 compares it with Metro's own report. If the reconciliation finds a classification problem, the site would have shown a wrong citywide number, which is the claim most likely to be quoted. Line pages carry the public numbers M2 needs.

</details>

## 5. How would you change it to…

…let the line list re-sort without a page reload, but still work without JavaScript?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Keep the server-rendered links (`?sort=reliability`) as the baseline, and add a small client component that intercepts the click, sorts the already-rendered list in place, and updates the URL with `history.replaceState`. Without JavaScript the link still loads the sorted page. Measure the JavaScript it adds against the section 7 budget first.

</details>
