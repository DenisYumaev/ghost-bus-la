# Quiz 022 · Schedule versions in force (`schedule_versions.py`)

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

Metro's current schedule (A) has been in force since Nov 15. On Dec 5 ingest downloads B, whose `feed_start_date` is Dec 13. Which version is in force on Dec 10, and on Dec 13? Why?

**Your answer:**

>

<details>
<summary>Model answer</summary>

A on Dec 10, and B on Dec 13. B's `valid_from` is the later of its `feed_start_date` (Dec 13) and the date first seen (Dec 5), so Dec 13. Versions are ordered by `valid_from`, not download order, so A's range ends the day before, on Dec 12. If B took over on Dec 5, its new trip IDs would match nothing Metro was actually running, and every trip for a week would look missed.

</details>

## 2. What does this do?

Why is "date first seen" the Los Angeles date of `first_seen_at`, not the UTC date?

**Your answer:**

>

<details>
<summary>Model answer</summary>

`valid_from` is compared with service dates, and service dates are Los Angeles dates (hard rule 5). A ZIP seen at 05:00 UTC on Mar 2 was seen at 21:00 PST on Mar 1. With the UTC date it would wrongly skip Mar 1. The fixed `@example` in the oracle test pins exactly this case, and a mutation to the UTC date fails two tests.

</details>

## 3. What breaks if…

…a version that loses a same-day tie were dropped from `dim_schedule_version`, as the first draft did?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Ingest downloads at 03:00 and on every restart. Suppose A is stored at 03:00, and the detector matches the morning's trips and sends alerts against A. A deploy at 14:00 then fetches a changed ZIP B, also valid from that day. On the next rebuild, A would vanish from the dimension, and the crosswalk rows and alert lineage keyed on A would point at nothing. Now A keeps its row with an empty range: never in force on rebuild, but still resolvable. The spec also says versions are never deleted.

</details>

## 4. What breaks if…

…Metro publishes a bad schedule B on Nov 20 and reverts to the old ZIP A's exact bytes on Nov 25?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Under the spec's current rule, a hash is dated from its earliest sighting, so A keeps its Nov 15 date and B stays in force after Nov 25. If B had different trip IDs, exact matching fails and trips look missed until someone notices the match rate dropping. The fetch log does record the re-sighting (a `duplicate` with A's hash), so the information exists. This is pinned by `test_known_limit_a_revert_to_old_bytes_is_not_detected` and recorded as an open question in SPEC section 10, not silently changed. Changing a spec rule needs a decision.

</details>

## 5. How would you change it to…

…make the property tests catch an implementation that just returns `[]`?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Structural properties (no overlaps, at most one version per day, order independence) all pass on an empty list. You need a property that says what the answer *is*. The suite now has a brute-force oracle: for each day, of the hashes whose start is on or before it, the latest start wins, then the latest sighting. The test asserts `version_in_force` agrees with it. Another property checks that every distinct hash gets exactly one row. Both fail on `[]`.

</details>
