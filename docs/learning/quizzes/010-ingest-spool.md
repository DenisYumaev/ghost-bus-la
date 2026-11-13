# Quiz 010 · PR #12 · Spool and fetch log

**How to take it:** write your answer under each question first, then open the model answer to compare. When you've finished, tell Claude, who grades your written answers and logs the score in `docs/learning/quiz-log.md`. You need 4 of 5 before M0 closes. A vague answer scores zero.

To reveal an answer: click **Model answer** on GitHub, or open VS Code's preview (`Cmd+Shift+V`) and click it there.

---

## 1. What does this do?

`Spool.write_snapshot` writes to `<name>.tmp`, calls `fsync`, renames to `<name>`, then `fsync`s the directory. What does each of the three steps guarantee?

**Your answer:**

>

<details>
<summary>Model answer</summary>

1. **Write to `.tmp`:** the file being written has a name no reader looks at. `pending()` only returns names ending in `.ndjson.gz`, so the uploader never sees a half-written file.
2. **`fsync` the file:** the operating system normally keeps writes in memory and flushes them later. `fsync` forces the bytes onto the physical disk *before* the name becomes visible. Without it, a power loss after the rename could leave a correctly named file full of zeros or garbage.
3. **Rename (`os.replace`), then `fsync` the directory:** a rename within one filesystem is **atomic**: readers see either the old state (no file) or the new state (the whole file), never a partial one. A file's *name* lives in its directory, so the directory must be fsynced too, or a crash could undo the rename and lose the file even though its bytes were on disk.

Together: after `write_snapshot` returns, the snapshot survives a crash, and before it returns, nothing half-done is visible.

**Must mention for full credit:** temp name hides partial writes; file fsync puts the bytes on disk before the rename; the rename is atomic; the directory fsync makes the rename itself durable.

</details>

---

## 2. What does this do?

What are the three possible `outcome` values on a `fetch` line, and what does the pipeline later use `network_error` lines for?

**Your answer:**

>

<details>
<summary>Model answer</summary>

- **`written`:** a snapshot was stored in the spool (and will be uploaded).
- **`duplicate`:** the local shortcut fired: the bytes equal the feed's previous snapshot, so nothing was stored. That's still a successful attempt.
- **`network_error`:** there was nothing to write. Either the connection was down for the whole interval (`error: "disconnected"`), or it was up but the server sent nothing (`error: "no_messages"`).

**What `network_error` is for:** it records that an attempt *happened and failed*. The pipeline uses that to tell an **outage** from a **quiet feed**. If no snapshot exists for a window *and* the fetch log shows `network_error`, trips in that window become `unknown`, not `missed`, so outages don't inflate missed-trip numbers. The capture SLO also counts these lines: an attempted, logged failure counts as captured; a missing line doesn't (infra spec, section 8).

**Must mention for full credit:** the three outcomes with meanings; network_error separates an outage from a quiet feed (`unknown` versus `missed`), and it feeds the capture SLO.

</details>

---

## 3. What breaks if…

`self._last_sha[snap.feed] = snap.sha256` were moved *above* the write, so it runs before the file is stored. A write fails with "disk full", and the next cut produces the same bytes. What happens, and which test catches it?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The failed write has already recorded its hash as "the last stored snapshot." The next cut has the same content, so the shortcut says `duplicate` and **stores nothing**. But nothing was ever stored. The snapshot is lost, and the fetch log *claims* a successful duplicate, so the gap is invisible.

It's worse because it repeats: as long as content stays the same (a quiet feed at 3 a.m.), every cut is skipped.

**Caught by:** `test_a_failed_write_does_not_poison_the_duplicate_shortcut`, which simulates a failed rename and then asserts the same snapshot is `written`. That planted bug was run in this PR, and the test failed as expected.

The general rule: **update "what's done" state only after the action succeeds.** It's the same reason the uploader writes the `.uploaded` marker only after S3 confirms.

**Must mention for full credit:** the failed write is remembered as stored; later identical snapshots are skipped, so data is lost and the log lies; the named test; the principle of updating state after success.

</details>

---

## 4. What breaks if…

The spool named files by the hash only (`<sha16>.ndjson.gz`), without the cut time. Name two things that break.

**Your answer:**

>

<details>
<summary>Model answer</summary>

1. **Ordering:** `pending()` and the detector (M3) process files oldest first by sorting names. Hash names sort randomly, so the detector could see 7:41's cancellation snapshot before 7:40's, and diff events in the wrong order (a cancellation appearing, then disappearing, then appearing).
2. **Collisions across time:** two snapshots with identical content at different cuts (a quiet feed) would get the **same file name**. The second write would overwrite the first, and if the first had already been uploaded and marked, the marker would apply to the new file too. The spool would lose the fact that the same state was observed at two times. (S3 keys *are* hash-only by design, because there, deduplication is the goal.)

Also: the janitor's "older than 48 hours" rule and humans debugging an outage both benefit from seeing the time in the name.

**Must mention for full credit:** two of (processing order for the uploader and detector; the same name for identical content at different times, so overwrites and confused markers; debuggability and age-based cleanup).

</details>

---

## 5. How would you change it to…

The fetch log fsyncs after every line. At 3 snapshot lines a minute that's cheap, but suppose you added a log line for every *message* received (about 1,100 a second). How would you change the logging, and what durability would you give up?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**Change:** don't fsync per line at that rate. Batch: buffer lines in memory and flush plus fsync every N lines or every T seconds (for example, each second), or keep per-message counts in memory and log **aggregates** per snapshot instead. The current design already does this: `n_messages`, `n_unkeyed`. Better still, keep per-message detail out of the fetch log entirely. It's an audit of attempts, not a message trace, and Prometheus counters (M5) are the right tool for rates.

**What you give up:** with batching, a crash loses up to one batch window of log lines (say, the last second). For per-message trace lines that's acceptable. For the per-snapshot `fetch` lines it isn't, because they're the capture record. So keep those fsynced individually, and batch only the high-volume ones.

A strong answer notes the trade-off between fsync cost (each one waits for the disk) and durability, and that the fetch log should stay small and meaningful rather than becoming a firehose.

**Must mention for full credit:** batch or aggregate instead of a per-line fsync; the cost is losing up to one batch on a crash; keep per-snapshot lines individually durable because they're the capture record.

</details>
