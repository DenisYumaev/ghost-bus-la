# Quiz 035 · Line tables

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

A direction has trips A>B>C>D (3 trips), A>B>C (1) and A>B>E (1). In what order does `dim_line_stop` list the stops?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**A, B, E, C, D.** The main pattern is A>B>C>D (most trips), so A, B, C and D sit at 1, 2, 3 and 4. E isn't on it. In its own trip, A>B>E, it comes after B (index 2), and no main-pattern stop follows it, so it goes half a step past B: 2.5. A rider on the branch sees E right after B, where the branch leaves the trunk. A first draft averaged each trip's own 0–1 position instead. That gave A, B, C, D, E here, but put trunk stops out of order when a short turn started mid-route.

</details>

## 2. What does this do?

Why do the line tables read only the schedule version in force on the last synced day?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Trick question: they don't. They're built for every version ever in force, keyed by `schedule_version`, and the API picks the version in force on the rider's own local date. Using only the last synced day's version would go wrong at a service change or after a backfill. New stops would be rejected, and removed stops accepted, so commutes on them could never match a trip and their alerts would silently never fire.

</details>

## 3. What breaks if…

…the headsign came from `trip_headsign`, as in most GTFS feeds?

**Your answer:**

>

<details>
<summary>Model answer</summary>

It's empty for every Metro trip, so every direction would have a NULL headsign. The API requires a headsign with every `direction_id` (API spec section 1), and the `not_null` test on `headsign` would fail the build. The data carries it in `stop_headsign` instead, which is why the model reads the first stop's value.

</details>

## 4. What breaks if…

…the stop list used only the main pattern?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Stops served only by a branch or a short turn would vanish. A rider who boards there couldn't save a commute, because commute validation checks the stop belongs to the line and direction, and the stop picker wouldn't offer it. Listing every served stop, ordered by position, keeps them, and `in_main_pattern` lets the page de-emphasize them.

</details>

## 5. How would you change it to…

…show a branch as its own list instead of interleaving it?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Group by pattern instead of by line-direction: one list per stop pattern, ordered by `stop_sequence`, labelled by the pattern's last stop. Patterns that are prefixes of a longer one (short turns) can be folded into it. The grain becomes line × direction × pattern × stop sequence, and the picker shows "towards X" groups. It's more UI work, which is why v1 interleaves.

</details>
