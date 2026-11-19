# Quiz 038 · Publish engine

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

The last successful load of `reliability` had 25,050 rows; tonight's has 19,000. What happens?

**Your answer:**

>

<details>
<summary>Model answer</summary>

19,000 is 24% below 25,050, more than the 20% limit, so the load is refused. `serving.reliability__new` is dropped, the live table keeps serving last night's 25,050 rows, and a failed `ops.publish_run` row records "19000 rows against 25050 last time". The other tables still publish, and the run exits non-zero so the alert fires. If the drop is real (say, a service cut), rerun with `--force`.

</details>

## 2. What does this do?

Why are index names suffixed with part of the run ID?

**Your answer:**

>

<details>
<summary>Model answer</summary>

An index keeps its name when its table is renamed. If the index on `reliability__new` were called `reliability_pk`, then after the swap the live table owns `reliability_pk`. The next publish would then try to create `reliability_pk` on the new staging table and fail, because index names are unique per schema. A per-run suffix makes every load's names new.

</details>

## 3. What breaks if…

…the three swap statements ran in autocommit mode?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Between "rename live to `__old`" and "rename `__new` to live" there is no table with the live name, so API requests in that gap fail. And if the `publish_run` insert failed after the renames, they would stay done, with no record of the load. In one transaction, readers see the old table until commit, and any failure undoes all three statements (a test checks exactly that).

</details>

## 4. What breaks if…

…an unknown DuckDB type were mapped to `text` instead of raising?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Say a gold column became a DECIMAL or a list. It would quietly land in Postgres as text: the API would return `"0.051"` instead of `0.051`, sorting would be alphabetical, and the OpenAPI contract test might not notice until a client broke. Raising makes the type change a deliberate one-line change to `PG_TYPES`, with a test.

</details>

## 5. How would you change it to…

…publish all serving tables as one atomic set, so the line list and the grid always match?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Load every `__new` table first, validate them all, then do every table's renames and `publish_run` rows in a single transaction. Readers would then see either the whole old set or the whole new set. The cost is a longer exclusive lock at swap time, and one bad table holds back all of them. ADR-007's "Would change if" names a versioned schema (`serving_v<n>` behind a pointer) as the cleaner way if this is ever needed.

</details>
