# Quiz 008 · PR #9 · Recorded WebSocket fixtures and loop timing

**How to take it:** write your answer under each question first, then open the model answer to compare. When you've finished, tell Claude, who grades your written answers and logs the score in `docs/learning/quiz-log.md`. You need 4 of 5 before M0 closes. A vague answer scores zero.

To reveal an answer: click **Model answer** on GitHub, or open VS Code's preview (`Cmd+Shift+V`) and click it there.

---

## 1. What does this do?

What two numbers from `docs/research/ws-cycle-timing.md` justify the rule "a snapshot is complete if the connection stayed up for the whole interval," and how do they justify it?

**Your answer:**

>

<details>
<summary>Model answer</summary>

- **The slowest reappearance of any entity: 6.74 s** (trip updates; 5.90 s for vehicles). Every entity the server is sending shows up again at least that often.
- **The shortest snapshot interval: 30 s** (vehicle positions; trip updates are 60 s).

Since 30 s is more than four times 6.74 s, an uninterrupted interval is guaranteed to contain at least four full loops, so every entity the server was sending appears at least once. Being connected the whole time is therefore enough to call the snapshot complete. No in-stream loop marker is needed, and none exists.

A good answer may also mention that 99% of the fleet arrives within about 4 s of connecting.

**Must mention for full credit:** the max gap (about 6.7 s); the 30 s interval; the conclusion that several loops fit in any uninterrupted interval.

</details>

---

## 2. What does this do?

The fixture keeps only 25 entities out of about 4,000, yet keeps *every* frame for those 25. Why keep all their frames instead of, say, the first 300 frames of the recording?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The first 300 frames would all come from the **initial burst**, the first fraction of a second, where each entity appears **once**. A test built on that couldn't exercise:

- **latest message wins**, which needs the same entity to appear several times with different content;
- **real timing:** gaps between appearances, entities joining late, and how many loops fit in an interval;
- **snapshot boundaries** across a 45-second span.

Filtering by *entity* rather than by *time* keeps the stream's real structure for those entities (each one keeps its own loop) while shrinking the file from 82 MB to about 4 KB. The contract test checks these properties so a careless re-trim can't remove them.

**Must mention for full credit:** the first N frames are one burst with no repeats; whole entities keep repeats, timing, and late joiners; that's what the snapshot logic needs to be tested on.

</details>

---

## 3. What breaks if…

`trim_ws_fixture.py` used `gzip.compress(data)` with the default settings instead of `mtime=0`. What would change, and why does it matter for a committed fixture?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The gzip header includes a **modification time**. By default it's the current time, so running the trimmer twice on the same recording would produce files whose bytes differ: the same content, a different header.

Consequences:

- Every re-run shows the fixture as **changed in git**, and adds a new binary blob to history forever, even though nothing meaningful changed.
- You can't check that a fixture was regenerated correctly by comparing bytes (the `cmp` check run in this PR would fail).
- The same principle matters far more in ingest. Bronze snapshots use a fixed gzip header so identical content gives **identical files**. Snapshots are keyed on the hash of the *uncompressed* bytes, so the key would still match, but the stored file wouldn't be reproducible, which defeats rebuild-and-compare checks.

**Must mention for full credit:** the header timestamp makes output differ between runs; noisy git diffs and history; reproducibility, which links to ingest's fixed-header rule.

</details>

---

## 4. What breaks if…

The recording found **0** frames without an `id`. Ingest will key its buffer by `id`. Suppose next month Metro starts sending occasional frames with no `id` (for example a `{"type": "heartbeat"}` keepalive). What should ingest do with them, and what must it *not* do?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**Must not:** drop them silently, or crash the stream loop. Dropping breaks the raw-archive promise (ADR-001 decision 2: store what arrived, parse later). A crash on an unexpected message would stop archiving every feed, which breaks hard rule 3 ("the archive comes first").

**Should:** still store the frame, unchanged, in the snapshot, under a synthetic key that can't collide with real IDs, for example `_noid:<sha256 of the bytes>`. The same bytes then deduplicate, and different ones are kept. Count them (`n_unkeyed` in the fetch log) so the change is visible. The schema-fingerprint check downstream (pipeline spec, section 10) then flags the new shape for a human, and decode routes it to quarantine rather than losing it.

This is why "every frame has an `id`" is a **measured** fact, not an assumption the code relies on.

**Must mention for full credit:** never drop or crash; store unchanged under a collision-free synthetic key; count it so it's visible; downstream drift detection or quarantine handles meaning.

</details>

---

## 5. How would you change it to…

The size estimate came from one 45-second evening sample. How would you design the full-day measurement M0 requires, and what could make the evening sample misleading?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**Design:** don't record separately. Let production ingest run for 24 hours and **read the fetch log**: every snapshot's row has the uncompressed `bytes`, and the compressed object size can be logged alongside, or read from S3 listings of the `dt=` partition. Then compute, per feed: snapshots attempted and written, total and percentile sizes raw and gzip, and size by hour of day. Commit the query as a script so the numbers trace to code (hard rule 11), and record the results in ADR-021 when it's accepted.

**Why the evening sample can mislead:**

- **Time of day:** the 7 p.m. fleet differs from the 8 a.m. peak (more vehicles, more trips with long stop-time predictions) and from 3 a.m. (few). Size scales with active trips.
- **Weekday versus weekend** schedules.
- `trip_updates` lists **today and tomorrow**, so its size shifts around midnight.
- **Compression ratio** varies with content; 15× on one sample may not hold.
- One 45 s window is a tiny sample, with no measure of variance.

**Must mention for full credit:** a 24-hour measurement from production's fetch log (or S3 sizes) with a committed script; at least two reasons the sample is biased (time of day, weekday or weekend, the today-plus-tomorrow window, variable compression).

</details>
