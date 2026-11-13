# Quiz 007 · PR #8 · Conditional-write self-test

**How to take it:** write your answer under each question first, then open the model answer to compare. When you've finished, tell Claude, who grades your written answers and logs the score in `docs/learning/quiz-log.md`. You need 4 of 5 before M0 closes. A vague answer scores zero.

To reveal an answer: click **Model answer** on GitHub, or open VS Code's preview (`Cmd+Shift+V`) and click it there.

---

## 1. What does this do?

List the five checks `scripts/selftest_conditional_writes.py` runs, and say which two ADR-004 `VERIFY` items they settle.

**Your answer:**

>

<details>
<summary>Model answer</summary>

1. A `PutObject` with `If-None-Match: *` to a fresh key under `selftest/` is **written** (200).
2. A second conditional write to the same key is **rejected with 412**.
3. The stored object still holds the **first** body.
4. A `PutObject` **without** `If-None-Match` is **denied (403 AccessDenied)** by the bucket policy.
5. Exactly **one version** of the key exists.

Then it deletes every version and delete marker it created.

**VERIFY items:**

- (a) Conditional writes return 412 on a **versioned** bucket, without quietly creating a new version: checks 2, 3, and 5.
- (b) The `s3:if-none-match` deny statement works as written: check 4.

**Must mention for full credit:** all five checks (roughly); which checks settle which of the two items.

</details>

---

## 2. What does this do?

The unit tests never touch AWS. What is botocore's `Stubber`, and what does `stubber.assert_no_pending_responses()` prove that a plain "the function returned the right thing" assertion doesn't?

**Your answer:**

>

<details>
<summary>Model answer</summary>

`Stubber` wraps a real boto3 client and intercepts its calls. Each `add_response` or `add_client_error` queues one canned reply, plus optionally the **exact parameters** the call must be made with. Calls are matched **in order**. A call with the wrong parameters, an unexpected call, or a call to the network raises an error. So the tests run offline (hard rule 10), with fake credentials.

`assert_no_pending_responses()` checks that **every queued response was consumed**, meaning the code made *all* the calls it was expected to make. The key case is cleanup: the test `test_cleanup_runs_even_when_a_check_raises` queues the cleanup calls. If the `finally:` block were removed, the function would still raise the expected error, but the cleanup responses would be left unused and the test would fail. That catches the bug "we leak test objects when something goes wrong."

Matching `expected_params` also pins down that the conditional writes really send `IfNoneMatch="*"` and the unconditional one doesn't.

**Must mention for full credit:** Stubber queues canned responses and checks parameters and order offline; "no pending" proves every expected call happened, such as cleanup.

</details>

---

## 3. What breaks if…

`conditional_put` treated **any** `ClientError` as "duplicate" instead of only status 412. Give a concrete failure in the real ingest uploader, which will use the same logic, and what it would do to the archive.

**Your answer:**

>

<details>
<summary>Model answer</summary>

Every failure would be recorded as success. Examples:

- **`403 AccessDenied`:** the instance role loses `s3:PutObject` (a bad Terraform change), or someone sends an unconditional write that the policy denies.
- **`500` or `503`:** S3 has a transient error.
- **Throttling** (`SlowDown`).

In each case the uploader would log `duplicate`, count it as **success**, write the `.uploaded` marker, and eventually the janitor would **delete the spool file**. The snapshot exists nowhere: it's not in S3, and it's no longer on disk. That's silent, permanent data loss, and the fetch log would *claim* it was stored, so even the capture SLO would look fine.

Only 412 means "these bytes are already safe," because the key is the content hash. 409 means retry. Everything else must raise, so the file stays in the spool and is retried.

**Must mention for full credit:** non-412 errors such as 403 or 5xx are misread as success; the spool file is marked uploaded and later deleted, so the data is lost; the logs lie; only 412 proves the bytes are stored.

</details>

---

## 4. What breaks if…

The self-test's `_require_selftest_key` guard were removed and someone ran it with `--key bronze/vehicle_positions/test.txt` (imagine that option existed). What would happen at each step, given the bucket policy?

**Your answer:**

>

<details>
<summary>Model answer</summary>

1. **Conditional write to `bronze/…`:** allowed. The role or user has `PutObject`, and `If-None-Match` is present. A junk test object is now in **bronze**.
2. **Second conditional write:** 412. **Unconditional write:** denied by `DenyUnconditionalWrites`, which covers `bronze/*`.
3. **Cleanup:** `DeleteObject` with a version ID on `bronze/*` is **denied** by `DenyBronzeDeletes`, for every principal, admin included.

Result: a test file sits in the permanent archive **forever**. It can't be deleted without a reviewed policy change. It would also pollute every downstream read of that feed's partition: decode would see a non-snapshot file.

This is exactly why the self-test uses `selftest/`, a prefix outside the deny-delete policy (pipeline spec, section 2.4), and why the guard refuses any other prefix *before* sending a request. The unit test `test_conditional_put_refuses_any_key_outside_selftest` keeps the guard from being removed silently.

**Must mention for full credit:** the first write succeeds into bronze; the cleanup delete is denied by the bucket policy; the junk object is permanent; the guard and its test prevent it.

</details>

---

## 5. How would you change it to…

The ingest uploader will need the same `conditional_put` logic, but hard rule 3 says ingest can't import app code, and `scripts/` isn't a package. How would you share or duplicate it, and how would you keep the two copies from drifting apart?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**Options:**

- **Duplicate on purpose:** ingest gets its own `conditional_put` in `services/ingest/src/ghostbus_ingest/`. It's about 20 lines, and the rule that ingest depends on nothing shared is worth more than avoiding a small copy. *Recommended.*
- **Move it into ingest and have the script import from ingest:** the self-test then exercises the *actual* production code. Allowed, because the rule restricts what ingest imports, not who imports ingest. The script would then depend on the ingest package being installed, which it is in the workspace.
- **Put it in `ghostbus_core`:** **not allowed**, since ingest can't import core (the isolation test would fail).

**Preventing drift** (if duplicated): one shared, table-driven test of the status-code contract (200 written, 412 duplicate, 409 retry, anything else raises) run against both implementations, or a test that the script's behavior matches ingest's on the same Stubber script. Or choose option 2, so there's only one copy.

A strong answer notes that option 2 is better for the self-test's *purpose*, which is proving production behavior, and that it should be done when the uploader PR lands.

**Must mention for full credit:** core is ruled out by hard rule 3; a concrete choice (duplicate, or move into ingest and import from there); a way to keep the behavior identical (a shared contract test, or a single copy).

</details>
