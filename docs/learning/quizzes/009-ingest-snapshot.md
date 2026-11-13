# Quiz 009 · PR #10 · Snapshot core (`ghostbus_ingest/snapshot.py`)

**How to take it:** write your answer under each question first, then open the model answer to compare. When you've finished, tell Claude, who grades your written answers and logs the score in `docs/learning/quiz-log.md`. You need 4 of 5 before M0 closes. A vague answer scores zero.

To reveal an answer: click **Model answer** on GitHub, or open VS Code's preview (`Cmd+Shift+V`) and click it there.

---

## 1. What does this do?

Walk through `SnapshotBuffer` for this sequence, with a 60 s interval starting at 960 and the connection up since 960: frame for `a` at 965, disconnect at 970, connect at 1010, frame for `b` at 1011, `cut(1020)`. What are `connected_s`, `partial`, and `n_entities`, and how is `connected_s` computed?

**Your answer:**

>

<details>
<summary>Model answer</summary>

- `on_connect(960)` sets `_connected_since = 960`.
- `on_message(a, 965)`: `a` is stored.
- `on_disconnect(970)` adds `970 - max(960, 960) = 10` s to `_connected_s` and clears `_connected_since`.
- `on_connect(1010)` sets `_connected_since = 1010`.
- `on_message(b, 1011)`: `b` is stored.
- `cut(1020)`: still connected, so it adds `1020 - max(1010, 960) = 10`. **`connected_s = 20`**.

The interval is `1020 - 960 = 60` s, and 20 < 60, so **`partial = True`**. Both frames are in the buffer, so **`n_entities = 2`**: a snapshot is written with what arrived.

After the cut, the interval restarts at 1020. The still-open connection carries over, and its time now counts from 1020 because of the `max(..., interval_start)`.

**Must mention for full credit:** 20 s from the two connected spans; partial because 20 < 60; 2 entities; the `max(connected_since, interval_start)` clipping.

</details>

---

## 2. What does this do?

`next_grid_point(now, interval)` returns `(floor(now / interval) + 1) * interval`. Why compute the next cut from the clock rather than as "previous cut + interval," and what does the test `test_grid_does_not_drift_when_cuts_run_late` prove?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Cuts always land on wall-clock multiples (:00 and :30 for a 30 s interval) **no matter how late the previous cut ran**.

If the next cut were "previous cut + interval" measured from when the cut *finished*, every small delay (gzip, disk write, a busy CPU) would push the schedule later: drift. Over a day, snapshots would wander off the grid, intervals would stop being exactly 30 s, and you couldn't line up snapshots across feeds or days.

The test runs 100 cuts that each finish 0.7 s late, and asserts the points are still exactly 1020, 1050, 1080, and so on. Computing from the clock self-corrects every time.

Aligning to the epoch also makes cut times predictable, which the spool file names (`YYYYMMDDTHHMMSSZ`) and the "99% of scheduled polls attempted" acceptance test rely on.

**Must mention for full credit:** clock-based points don't accumulate delay; "previous + interval" drifts; the test's 100 late cuts stay exactly on the grid.

</details>

---

## 3. What breaks if…

Someone "simplifies" `cut` to store each message after `json.loads` then `json.dumps`, so the lines look tidy and consistent. Name two things that break, and which test catches it.

**Your answer:**

>

<details>
<summary>Model answer</summary>

**What breaks:**

1. **The raw-bytes rule** (ADR-001 decision 2, restated in ADR-021): bronze would hold *our* re-serialization, not what Metro sent. Whitespace, key order, number formatting (`6.169152` could become a different float string), and escaping can change. A future parser bug could no longer be fixed by re-reading the true original, and evidence of exactly what Metro sent is gone.
2. **Frames without an `id`, or invalid JSON,** couldn't be `json.loads`-ed at all, so they'd crash the loop or be dropped, both of which the design forbids.

Also: hashes would change whenever the Python version changed `json.dumps` defaults, so identical content across versions could stop deduplicating.

**Caught by:** `test_lines_are_the_received_bytes_unchanged_and_sorted_by_entity`, which compares lines to the exact input bytes, and `test_unkeyed_frames_are_stored_and_counted_never_dropped`, which feeds `b"garbage"` and expects it stored verbatim. With real data, Metro's spacing (`"id": "9504"`) would differ from `json.dumps` output too.

**Must mention for full credit:** two of (raw fidelity lost; invalid or id-less frames crash or drop; hashes unstable across versions); at least one test that catches it.

</details>

---

## 4. What breaks if…

The lines were joined in **arrival order** instead of sorted by entity ID. The Hypothesis test caught it in this PR. Explain what Hypothesis did, and what the consequence would be in production for S3 storage and for the conditional write.

**Your answer:**

>

<details>
<summary>Model answer</summary>

**Hypothesis** generated many random cases: random lists of entity IDs and random shuffles of the same messages. It checked the property "the same set of messages in any order gives identical `data`, `sha256`, and `gz`." Without sorting, some shuffle produced different bytes, the property failed, and Hypothesis reported (and shrank to) a minimal failing example. That's broader than a hand-picked test: it searches for the counterexample.

**In production:** the server's loop order and reconnects change arrival order, so two snapshots of an **identical fleet state** would have different bytes, different hashes, and **different keys**. Both would be stored, the duplicate detection (the local shortcut and the S3 `412`) would never fire, and storage would grow with redundant copies. Worse, "same content gives same key" is the foundation of idempotency (hard rule 2). Retries and replays stay safe only because the key depends on content alone.

**Must mention for full credit:** Hypothesis generates many inputs and checks a property (finding a counterexample); identical states get different hashes, keys, and duplicates; deduplication and idempotency silently stop working.

</details>

---

## 5. How would you change it to…

Right now a reconnect 25 s before a cut is marked `partial`, even though the data shows the whole fleet arrives within about 4 s of connecting. How would you change the rule to mark such snapshots complete, what evidence would you want first, and what's the risk?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**Change:** mark a snapshot complete if the connection was up continuously for at least `FULL_CYCLE_S` before the cut (for example 10 s, about 1.5 times the measured maximum gap of 6.74 s), even if it dropped earlier in the interval. In code: track the time of the *last* connect. At `cut`, `complete = connected now and (at - last_connect) >= FULL_CYCLE_S`. Keep logging `connected_s`. Add tests at exactly 10 s and just under. Record the change in a new ADR (ADR-021 decision 4 changes).

**Evidence first:**

- The reappearance-gap distribution over a **full day**, including peak hours and the post-midnight period, not one evening.
- How the server behaves *after a reconnect*: does the burst always deliver the whole fleet?
- Confirmation from decode or gold that snapshots called complete under the new rule never miss trips that were running.

**Risk:** if the server's loop slows (a bigger fleet, a busy server), entities could be missing from a snapshot marked complete. Downstream would then read "absent" as "left the stream" instead of "not observed," which inflates `missed` trips, exactly the false finding the `partial` flag exists to prevent. The current rule is conservative and costs only a little precision, so the change should be judged by how much data it actually recovers.

**Must mention for full credit:** a concrete rule (continuous connection of at least N s before the cut); evidence (a full-day gap distribution, reconnect-burst behavior); the risk (false completes become false missed trips); a new ADR.

</details>
