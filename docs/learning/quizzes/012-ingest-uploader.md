# Quiz 012 · PR #14 · The uploader

**How to take it:** write your answer under each question first, then open the model answer to compare. When you've finished, tell Claude, who grades your written answers and logs the score in `docs/learning/quiz-log.md`. You need 4 of 5 before M0 closes. A vague answer scores zero.

To reveal an answer: click **Model answer** on GitHub, or open VS Code's preview (`Cmd+Shift+V`) and click it there.

---

## 1. What does this do?

Describe one `upload_once` round in order, and say why a single S3 failure ends the whole round instead of skipping to the next file.

**Your answer:**

>

<details>
<summary>Model answer</summary>

1. **Janitor:** delete spool snapshots and fetch-log hours that are already in S3 and older than 48 hours. Local files only, and only ones with a matching upload marker.
2. **Snapshots, oldest first:** derive the key from the file name, read the bytes, and check that they match the hash in the name. A mismatch means the file is set aside as `.corrupt` and logged. Otherwise `conditional_put`: 200 or 412 means the `.uploaded` marker is written and an `upload` line logged.
3. **Fetch log:** upload each hourly file whose *current* content isn't in S3 yet (closed hours, or every hour on the final pass), under a content-addressed key, then record its hash in the marker.

**Why stop at the first failure:** a failure almost always means S3 or the network is down, or permissions are broken. That affects *every* file equally. Continuing would hammer a failing service with hundreds of doomed requests, fill the log with errors, and spend the retry budget. Stopping, then letting `run()` back off (1 s, 2 s, 4 s, up to 60 s), retries gently, and nothing is lost because the files stay in the spool.

**Must mention for full credit:** the janitor, snapshot uploads, and fetch-log uploads in order; the hash check; the marker only after 200 or 412; stopping because failures are systemic, with backoff in `run()` and files kept in the spool.

</details>

---

## 2. What does this do?

How does the uploader decide that a fetch-log hour needs uploading, and why can the same hour end up as **two** objects in S3?

**Your answer:**

>

<details>
<summary>Model answer</summary>

`files_to_upload` lists every hourly file. It includes a file if its hour is **closed** (the hour's end is at or before `now`) or this is the **final** pass at shutdown. It then skips the file if the SHA-256 stored in its `.uploaded` marker equals the SHA-256 of the file's **current** content. So a file is uploaded whenever its content differs from what was last uploaded.

**Two objects for one hour:** ingest shuts down mid-hour, and the final pass uploads hour 02 as it was (key `…/hour=02/<hash A>.jsonl`). After the restart, more lines are appended to the same local file. When hour 02 closes, its content has changed, so it's uploaded again under a new key (`…/<hash B>.jsonl`). Both are kept, because the conditional write would reject reusing one fixed name (quiz 003, question 4). Readers take the **union** of an hour's objects and drop duplicate lines (B contains all of A).

**Must mention for full credit:** closed or final; the marker's hash versus the current content's hash; a restart mid-hour plus later lines produce new content, a new key, and a second object; readers take the union.

</details>

---

## 3. What breaks if…

The marker were written *before* `conditional_put` instead of after. Which tests failed when this was planted, and what would it cost in production during an S3 outage?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**Tests that failed (5):** `test_an_s3_failure_keeps_the_file_and_stops_the_round` (all three failure types: 503, 403, connection error), `test_uploads_resume_after_an_outage`, and `test_run_backs_off_on_failure_and_does_a_final_pass_on_stop`.

**In production:** during an outage, each pending file gets marked "uploaded" just before its upload fails. `pending()` no longer returns it, so it's **never retried**. After 48 hours the janitor deletes it as "safely in S3." Every snapshot from the outage window is permanently lost, which is exactly the scenario the spool exists to survive ("block S3 for 10 minutes; confirm the spool drains," the M0 chaos drill). The fetch log would show `error` upload lines, but nothing would retry.

The general rule, again: **record "done" only after it's done.** It's the same pattern as the duplicate shortcut (quiz 010) and, later, the alert outbox (M3).

**Must mention for full credit:** the failing tests (at least the outage and resume ones); files marked during an outage are never retried and are later deleted, so the outage's data is lost; record success only after confirmation.

</details>

---

## 4. What breaks if…

The hash check before upload were removed, and a disk error flipped some bytes in a spool file. What would be stored in S3, and why is that worse than losing the snapshot?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The file's **name** still carries the original hash, so its key would be `bronze/<feed>/dt=…/<original sha16>.ndjson.gz`, but the **bytes** under that key would be corrupt. Then:

- The key **lies**: content addressing promises "the bytes at this key hash to this name," and every later consumer trusts that.
- If the correct bytes ever arrive later (a replay or backfill), the conditional write returns **412** because the key is taken, so the corrupt version **wins forever**. Bronze denies deletes and overwrites, so it can't be fixed without a reviewed policy change.
- Decode might fail on it (invalid gzip), or worse, parse wrong data silently.

Losing one snapshot is a visible, bounded gap that the fetch log explains. A corrupt object under a trusted key is silent, permanent, and blocks the correct data. With the check, the file is renamed `.corrupt` (kept for investigation, never uploaded) and logged with outcome `corrupt`.

**Must mention for full credit:** the key promises a hash the bytes don't match; it permanently blocks the correct bytes (412 plus deny-delete); silent and permanent is worse than a visible gap; set aside and logged instead.

</details>

---

## 5. How would you change it to…

The janitor deletes uploaded spool files older than 48 hours. In M3, the **detector** reads trip-update snapshots from the spool. How would you change the janitor so it never deletes a file the detector hasn't processed yet, and how would you test it?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**Change:** the detector records a **cursor**: the name of the last spool file it has fully processed, written atomically (temp file, then rename) to `<spool>/_cursors/detector.trip_updates`. Spool names sort by cut time, so "processed" means `name <= cursor`. `clean_uploaded` gains a condition, delete only if **uploaded and older than 48 h and behind the cursor**. If there's no cursor file (the detector has never run), treat the cursor as "nothing processed" and delete nothing for that feed, or apply the rule only to `trip_updates`, since the detector doesn't read vehicle positions.

This is the third condition the spec names (section 2.4, step 5), deferred in this PR because the detector doesn't exist yet.

**Test first:** three uploaded files older than 48 h, and a cursor pointing at the middle one. Run the janitor. Assert the first two are deleted and the third is kept. Add a case with no cursor file (nothing deleted for that feed), and one where a file is behind the cursor but *not* uploaded (kept).

**Must mention for full credit:** a persisted, atomically written detector cursor compared with the sortable spool names; delete only when uploaded and old and processed; the missing-cursor case; a test with a cursor in the middle of the files.

</details>
