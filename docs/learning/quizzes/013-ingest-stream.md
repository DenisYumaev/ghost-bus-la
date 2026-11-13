# Quiz 013 · PR #15 · The WebSocket stream runner

**How to take it:** write your answer under each question first, then open the model answer to compare. When you've finished, tell Claude, who grades your written answers and logs the score in `docs/learning/quiz-log.md`. You need 4 of 5 before M0 closes. A vague answer scores zero.

To reveal an answer: click **Model answer** on GitHub, or open VS Code's preview (`Cmd+Shift+V`) and click it there.

---

## 1. What does this do?

`StreamRunner.run` starts two coroutines that share one `SnapshotBuffer`. What does each one do, and why is sharing the buffer safe without a lock?

**Your answer:**

>

<details>
<summary>Model answer</summary>

- **Connection loop:** opens the WebSocket (with the project User-Agent), records `connect`, passes every frame's exact bytes to `buffer.on_message`, and on close records `disconnect` with the close code. If the connection never opened, it records `connect_failed`. Then it waits `backoff(attempt)` and reconnects, until stop.
- **Cut loop:** sleeps until the next wall-clock grid point (`next_grid_point`), calls `buffer.cut(at)`, writes the snapshot to the spool, and logs the attempt. On stop, it makes one final cut to save frames received since the previous cut.

**Why no lock:** both are **coroutines in one asyncio event loop**, which runs on **one thread**. Only one coroutine runs at a time, and control switches only at an `await`. `buffer.on_message` and `buffer.cut` contain no `await`, so each runs to completion without the other interleaving. A thread-based design would need a lock. That's one reason asyncio suits this: many concurrent waits (sockets, timers), no shared-memory races.

**Must mention for full credit:** what each loop does (receive and reconnect; cut on the grid and write); one thread with switches only at `await`, so buffer operations can't interleave.

</details>

---

## 2. What does this do?

The live smoke test showed the first snapshot as `partial=True, connected_s=21.3` and the second as `partial=False, connected_s=30.0`. Explain both numbers.

**Your answer:**

>

<details>
<summary>Model answer</summary>

Ingest started at about 03:47:08.7 UTC. The buffer's first interval begins at the **previous grid point**, 03:47:00, not at start, so intervals stay aligned with the 30 s grid.

- **First cut, 03:47:30:** the interval is 03:47:00 to 03:47:30 (30 s), but the connection only existed from 03:47:08.7, so `connected_s` = about 21.3 s, which is less than 30. It's **partial**. That's correct: entities that appeared only in the first 8.7 s would be missing, and downstream must treat absence as "not observed."
- **Second cut, 03:48:00:** connected for the whole interval 03:47:30 to 03:48:00, so `connected_s = 30.0`. It's **complete**, and it held 1,599 vehicles and 3,769 trips.

This is also why a test asserting "some snapshot is partial" proved nothing: the first one is *always* partial.

**Must mention for full credit:** the first interval starts at the grid point before start, so connected time is less than the interval and it's partial; the second interval was fully connected, so it's complete.

</details>

---

## 3. What breaks if…

The reconnect test originally asserted `any(e["partial"] for e in fetches)`. When `buffer.on_disconnect` was deliberately removed, the test **still passed**. Why, and what was changed so it now fails on that bug?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**Why it passed:** the first snapshot after start is always partial, as in question 2. So "some snapshot is partial" was true *regardless* of whether disconnects were tracked. Also, the server dropped the connection after 50 frames (about 0.1 s), which was still inside that first, already-partial interval.

**The fix (two parts):**

1. Assert on the **specific interval that contains the logged disconnect**: find the `disconnect` time and the `fetch` line whose interval contains it, then assert that one is `partial=True` with `connected_s < 1`.
2. Move the drop to **about 1.5 s in** (1,300 frames), so it lands in an interval that would otherwise be complete.

With `on_disconnect` removed, the buffer believes the connection never ended, so that interval reads `connected_s = 1.0, partial = False`, and the test fails, as verified.

**The lesson:** a test that passes when you plant the bug it's meant to catch is worse than no test, because it gives false confidence. Mutation checks like this are how you find them.

**Must mention for full credit:** the first interval is always partial (and the drop happened inside it), so the assertion was trivially true; the fix targets the drop's own interval and moves the drop later; a test must fail when its bug is planted.

</details>

---

## 4. What breaks if…

The connection loop used `async for message in ws:` (which yields `str`) and stored `message.encode()`. For Metro's current frames this produces identical bytes. Why is `recv(decode=False)` still the right choice?

**Your answer:**

>

<details>
<summary>Model answer</summary>

`async for` makes the library **decode** each text frame's UTF-8 bytes into a Python `str`, and `.encode()` turns it back into bytes. For valid UTF-8 that round trip is lossless, which is why today's ASCII-only frames come out identical. But:

- It's an assumption about **someone else's data** (we measured 0 non-ASCII frames, but that's one evening). Invalid UTF-8 in a frame would make the library **raise and close the connection**, killing the stream. With `decode=False` we store whatever bytes arrived, and the snapshot logic handles them (the `_noid:` key).
- It does extra work on about 1,100 frames a second: decoding and re-encoding everything for nothing.
- It obscures intent. The rule is "store exactly what was received" (ADR-001 decision 2, ADR-021). `recv(decode=False)` says that literally; a decode-then-encode round trip invites someone to "clean up" the string in between.

**Must mention for full credit:** the round trip is only lossless for valid UTF-8; invalid bytes would crash the stream versus being stored; the raw-bytes rule (plus the wasted work).

</details>

---

## 5. How would you change it to…

The final cut on shutdown happens as soon as stop is set, while the connection is still closing, so frames arriving in those last milliseconds are lost. How would you change the order so the final snapshot includes everything received, and what would you test?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**Change:** make the final cut wait for the connection loop to finish. In `run()`:

1. On stop, the connection loop closes the socket, drains what's left, records `disconnect`, and returns.
2. **Then** the final cut runs, at `clock()`.

Concretely: have the cut loop exit on stop *without* cutting, and do `await self._connection_loop(stop)` then `self._cut(...)` in `run()`, after awaiting the cutter task. The final snapshot then covers every frame up to the close, and it's correctly marked partial if the disconnect came before the cut time (its `connected_s` ends at the disconnect).

**Test:** a fake server that sends a recognizable last frame right as the client starts closing (or a buffer spy recording the order of `on_message`, `on_disconnect`, and `cut`). Assert the final snapshot contains that frame, and that the `disconnect` log line comes **before** the final `fetch` line.

**Trade-off:** shutdown waits for the close handshake, bounded by websockets' `close_timeout` (10 s by default), which matters against Docker's stop timeout (10 s by default before SIGKILL). Set `close_timeout` lower, or Docker's `stop_grace_period` higher, so the final cut always happens.

**Must mention for full credit:** cut after the connection loop has finished; the final snapshot then includes the last frames and is partial-marked correctly; a test of ordering and contents; the shutdown-time bound against Docker's stop timeout.

</details>
