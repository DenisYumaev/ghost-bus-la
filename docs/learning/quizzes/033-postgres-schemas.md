# Quiz 033 · Postgres `serving` and `ops` schemas (ADR-007)

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

`CHECK ((status = 'succeeded') = (error IS NULL))` on `ops.publish_run`.

**Your answer:**

>

<details>
<summary>Model answer</summary>

It compares two booleans: "this run succeeded" and "there is no error". They must be equal, so a success has no error and a failure must have one. It's a compact "if and only if". Both sides are never NULL: `status` is NOT NULL and `IS NULL` always returns true or false. So the check can't pass by evaluating to NULL, which is how a CHECK on a nullable expression usually lets bad rows through.

</details>

## 2. What does this do?

Why does migration `0001` create the `serving` schema but no serving tables?

**Your answer:**

>

<details>
<summary>Model answer</summary>

ADR-007: `publish` recreates each serving table on every load (`__new`, then a rename swap), so it owns their definitions and indexes. If Alembic also created them, there would be two definitions of the same table, and the next publish would replace whatever the migration built. Alembic only makes sure the schema exists.

</details>

## 3. What breaks if…

…the rename swap ran as three separate statements without a transaction?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Between "rename live to `__old`" and "rename `__new` to live" there is no table with the live name, so an API request in that gap fails with "relation does not exist". If the process died there, the site would stay broken until someone fixed it by hand. In one transaction, Postgres DDL is transactional: readers see the old table until the commit, then the new one.

</details>

## 4. What breaks if…

…`ingest` were allowed to write `ops.feed_status`?

**Your answer:**

>

<details>
<summary>Model answer</summary>

`ingest` would need a database driver and credentials, and a Postgres outage or slow query could stall the archive. That breaks hard rule 3: ingest depends only on network, disk and S3. The CHECK on `updated_by` makes the rule visible in the schema, and ingest's own test fails if a database package is added to it.

</details>

## 5. How would you change it to…

…add a column to `ops.publish_run` without breaking the running release?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Expand, deploy, contract (API spec section 6). The new migration adds the column as nullable, or with a default, so the old code, which doesn't know about it, keeps working. Then deploy code that writes it. Only after that, if needed, a later migration adds NOT NULL or drops what's obsolete. Deploys aren't atomic, so each release must work with both the previous schema and the next.

</details>
