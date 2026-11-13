# Quiz 011 · PR #13 · Shared S3 write and backoff

**How to take it:** write your answer under each question first, then open the model answer to compare. When you've finished, tell Claude, who grades your written answers and logs the score in `docs/learning/quiz-log.md`. You need 4 of 5 before M0 closes. A vague answer scores zero.

To reveal an answer: click **Model answer** on GitHub, or open VS Code's preview (`Cmd+Shift+V`) and click it there.

---

## 1. What does this do?

`backoff_delay(attempt)` returns `min(60, 2**attempt) × (0.5 + 0.5 × random)`. Give the range of possible delays for attempts 0, 3, and 10, and explain what the jitter part is for.

**Your answer:**

>

<details>
<summary>Model answer</summary>

| Attempt | Base delay | Range with jitter |
| --- | --- | --- |
| 0 | 1 s | 0.5 to 1 s |
| 3 | 8 s | 4 to 8 s |
| 10 | 1,024 s, capped to 60 s | 30 to 60 s |

**Jitter** spreads retries out in time. Without it, every client that lost its connection in the same outage would retry at exactly 1 s, 2 s, 4 s, and so on, in lockstep, hitting the server in synchronized waves (the "thundering herd" problem) just as it's recovering. Here there's one client per stream, but the WebSocket and uploader threads both reconnect after a network blip, and Metro's server serves many clients. Being polite to someone else's server is a design rule (spec 2.3).

**Must mention for full credit:** the three ranges (roughly right, including the 60 s cap); jitter desynchronizes retries to avoid synchronized waves.

</details>

---

## 2. What does this do?

The self-test script used to have its own copy of `conditional_put`. Now it imports `ghostbus_ingest.s3.conditional_put`. Why is that better, and why doesn't it violate hard rule 3 ("ingest never imports app code")?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**Better:** the self-test's purpose is to prove that **production behavior** works against the real bucket. With a separate copy, the self-test could pass while ingest's own copy had a bug: two implementations can drift apart. Now one function is both tested offline (`test_s3.py`) and exercised against real S3 (`make selftest-s3`), and the self-test rerun in this PR passed through it.

**Not a violation:** hard rule 3 restricts what **ingest imports**: no shared app code, no database, nothing that could break the archive. Here a *script* imports *ingest*, which is the opposite direction. Ingest still imports nothing new (the isolation test still passes). Ingest depending on boto3 is fine: S3 is one of its three allowed dependencies (network, disk, S3).

**Must mention for full credit:** one copy means the self-test proves the real code and nothing can drift; the import direction is script to ingest, not ingest to app code; the isolation test still passes.

</details>

---

## 3. What breaks if…

Someone adds `403` to the statuses `conditional_put` treats as "duplicate," reasoning that "403 just means the policy blocked a write, so the object must exist." Trace what happens in production when the instance role accidentally loses `s3:PutObject` in a bad Terraform change.

**Your answer:**

>

<details>
<summary>Model answer</summary>

1. Every upload returns **403 AccessDenied** (the role can't write).
2. `conditional_put` reports `"duplicate"` for each one.
3. The uploader treats that as success: it writes the `.uploaded` marker and logs `outcome: duplicate`.
4. After 48 hours the janitor **deletes those spool files**, since they're marked as uploaded.
5. **Nothing reached S3.** Every snapshot since the bad change is permanently lost, and the fetch log claims they were stored, so no alert fires and the capture SLO looks perfect.

The reasoning is wrong because a 403 says nothing about whether the object exists. Only **412** means "something is at this key," and because the key is the content hash, that means *these bytes* are safe.

This PR's test `test_any_other_error_is_raised_never_treated_as_success[AccessDenied-403]` catches exactly this change: it was planted and failed.

**Must mention for full credit:** uploads fail with 403 but are marked uploaded; the janitor deletes them, so the data is lost; the logs claim success, so nothing alerts; only 412 proves presence; the test that catches it.

</details>

---

## 4. What breaks if…

`conditional_put` refuses keys that don't start with `bronze/` or `selftest/`, or that contain a `..` segment. What could go wrong without that check, given how the uploader derives keys from spool file names?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The uploader builds keys from spool directory and file names. Without the guard, a bug in that derivation could write anywhere in the bucket:

- **Into `derived/`:** overwriting or polluting rebuildable tables with raw snapshot bytes. The bucket policy doesn't require conditional writes there, so it could silently *replace* a real partition.
- **At the bucket root or an odd prefix** (`../bronze/x`, `/bronze/x`, a missing feed name producing `bronze//...`): objects that no reader expects, invisible to compaction, and they'd count against storage forever.
- **Path traversal** via a crafted name (`..`) is the classic way a "derive a path from input" bug becomes a security hole. S3 keys aren't filesystem paths, but readers and tools may treat them like paths.

The guard turns these into an immediate `ValueError` (the spool file stays put and the error is logged) instead of a silent wrong write. It's defense in depth: `Spool` already rejects unknown feeds, and this check doesn't trust that.

**Must mention for full credit:** a key-derivation bug could write outside bronze (for example, overwriting derived/, where unconditional writes are allowed); malformed or traversal keys; the guard fails loudly instead of writing wrongly.

</details>

---

## 5. How would you change it to…

`conditional_put` retries a 409 up to 3 times with a fixed 0.5 s sleep. How would you make that use `backoff_delay` instead, what test would you write first, and why does it barely matter for this system?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**Change:** replace `time.sleep(retry_delay_s)` with `sleep(backoff_delay(attempt))`, and inject `sleep` as a parameter (defaulting to `time.sleep`) so tests can record delays without waiting.

**First test:** stub three 409s followed by a 200, pass a fake `sleep` that records its arguments, and pin jitter with a fake `rand`. Assert the recorded delays follow the schedule (for example `[1.0, 2.0]` with `rand=lambda: 1.0` and the cap respected), and that the result is `"written"`. It fails before the change, because the delays would be `[0.5, 0.5]`.

**Why it barely matters:** a 409 means *another conditional write to the same key is in flight right now*. In this system there's **one uploader**, and keys are content hashes, so concurrent writes of the same key are very rare (a restart racing its own previous process, or a backfill overlapping live ingest). Those conflicts resolve within milliseconds. Fixed short retries are fine; exponential backoff mainly matters for *overload* errors (503 SlowDown), which correctly raise and are retried by the uploader loop with backoff.

**Must mention for full credit:** inject `sleep` and use `backoff_delay(attempt)`; a test with a fake sleep and pinned jitter asserting the delay sequence; 409s are rare here (one uploader, content-hash keys) and overload errors are handled by the loop's backoff.

</details>
