# Quiz 014 · PR #16 · The ingest service entry point

**How to take it:** write your answer under each question first, then open the model answer to compare. When you've finished, tell Claude, who grades your written answers and logs the score in `docs/learning/quiz-log.md`. You need 4 of 5 before M0 closes. A vague answer scores zero.

To reveal an answer: click **Model answer** on GitHub, or open VS Code's preview (`Cmd+Shift+V`) and click it there.

---

## 1. What does this do?

Walk through what happens, in order, when `docker stop` sends SIGTERM to a running ingest container.

**Your answer:**

>

<details>
<summary>Model answer</summary>

1. The asyncio signal handler (installed in `_main_async` with `loop.add_signal_handler`) calls `stop.set()`.
2. Each `StreamRunner` reacts. The cut loop wakes and makes its **final cut** (frames since the last grid cut go to the spool and the fetch log). The connection loop's `close_on_stop` closes the WebSocket with code 1000 ("ingest shutting down"), and the disconnect is logged.
3. `asyncio.gather` returns once both streams have finished.
4. `uploader_stop.set()` signals the uploader thread. Its `run()` loop exits and makes a **final pass** with `final=True`: uploads the remaining spool files *and* the still-open fetch-log hour.
5. The service waits for the thread (up to 60 s, via `asyncio.to_thread(join)` so the event loop isn't blocked), logs `service_stop` with exit code 0, and the process exits.

Order matters: streams first, then uploader, so the final pass includes the final snapshots.

**Must mention for full credit:** the signal sets stop; streams make final cuts and close; then the uploader's final pass (including the open log hour); exit 0; why that order.

</details>

---

## 2. What does this do?

Why does the uploader run in a **thread** while the streams run as asyncio **coroutines**? What would go wrong if the uploader ran in the event loop as-is?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**boto3 is synchronous (blocking):** a `put_object` call blocks its thread until S3 responds, which takes tens to hundreds of milliseconds normally, and up to the full timeout during an outage. If the uploader ran inside the event loop, every S3 call would **freeze the whole loop**: no frames received, no cuts on time. During an S3 outage, with connect timeouts and retries, the streams could stall for seconds or minutes, so snapshots would be cut late or show gaps. That's exactly the coupling the spool exists to prevent ("If S3 is unreachable it keeps spooling," spec 2.1).

A separate thread lets the blocking calls wait without stopping the loop. The streams and the uploader share only the spool directory, through atomic files and markers, so no shared in-memory state needs a lock.

The alternatives would be an async S3 client (a new dependency, which needs an ADR) or `asyncio.to_thread` per call. A dedicated thread is simplest.

**Must mention for full credit:** boto3 calls block; in the loop they'd stall frame reading and cuts, especially during an S3 outage; the thread isolates them; they share only files.

</details>

---

## 3. What breaks if…

A bug crashes the uploader thread, but `run_uploader` didn't catch it and stop the service. What would happen over the next few days, and how would you find out?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The streams would keep running and logging "written" snapshots, so everything **looks** healthy. But:

- Nothing is uploaded, so S3 gets no new bronze data.
- The janitor never runs (it lives in the uploader round), so **the spool grows**: about 0.65 GB a day.
- After some days, the 30 GB disk fills. Then spool writes fail (`spool_error`) and **data is lost from then on**, *and* everything still in the spool is at risk if the VM dies.

You'd find out late: through the spool-disk alert at 70% (ops PR), or a fetch-log check showing `written` with no matching `upload` lines.

**With the fix:** the crash logs `uploader_crashed`, sets stop, and the service exits with code **1**. Docker's restart policy starts a fresh process within seconds, and the new uploader resumes from the spool (markers show what's done). The test `test_a_crashed_uploader_stops_the_service_with_exit_code_1` covers it.

The principle is **fail loudly and restart** (crash-only software) rather than limping on with one part dead.

**Must mention for full credit:** streams continue but nothing uploads; the spool grows until the disk fills and data is lost; discovery is late; the fix exits with code 1 so Docker restarts it and the uploader resumes from the markers.

</details>

---

## 4. What breaks if…

At startup the service deletes **every** `.tmp` file in the spool (`older_than_s=0`), while the uploader's normal cleanup only deletes ones older than an hour. Why is "all" safe at startup and wrong later?

**Your answer:**

>

<details>
<summary>Model answer</summary>

A `.tmp` file exists only *during* a spool write: it's created, fsynced, then renamed within milliseconds.

- **At startup** no write is in progress, because the streams haven't started. So any `.tmp` that exists **must** be debris from a process that crashed mid-write. Its contents were never published (the rename didn't happen), so deleting it loses nothing, and removing it immediately keeps the spool clean. One process runs per spool, so nothing else could be writing.
- **While running**, a `.tmp` might belong to a write happening *right now*. Deleting it would make the in-progress rename fail (`os.replace` with a missing source), turning a healthy write into a `spool_error`. Hence the age threshold: a temp file older than an hour can't be a live write.

This only holds with **one ingest process per spool**: two processes sharing a spool would break the startup rule. The infra design guarantees one (a single container with restart policy).

**Must mention for full credit:** at startup no writes are in flight, so every temp file is crash debris and unpublished; at runtime a temp file may be a live write, which deleting would break; the one-process-per-spool assumption.

</details>

---

## 5. How would you change it to…

Right now a misconfigured service (no `GHOSTBUS_BUCKET`) exits with code 2 immediately, and Docker's `restart: always` restarts it again and again. How would you make that failure obvious instead of a silent restart loop, and what would you test?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**Options, often combined:**

- **The external heartbeat catches it.** A crash-looping service never completes a cycle, so it never pings, and `ingest_heartbeat_missed` fires within minutes. That's why the heartbeat exists (infra spec, section 9), and it comes in the deploy PR.
- **A deploy-time check:** `deploy.sh` runs the container once with a "check config and exit" mode (for example `python -m ghostbus_ingest --check`) *before* swapping, and fails the deploy, keeping the old version running, if it exits non-zero. Bad config then never reaches production.
- **Docker restart policy:** `restart: on-failure` with backoff, or a health check, makes `docker ps` show `Restarting (2)`. The config error is the last log line.
- **Distinct exit codes:** 2 for config and 1 for a crash, so monitoring can tell "won't ever work" from "a transient bug."

**Test:** a unit test that `--check` with missing or bad settings returns 2 and logs `config_error` naming the variable (like the existing `test_main_exits_2...`), and with good settings returns 0 **without** opening any connection or contacting S3. The deploy smoke test then exercises it for real.

**Must mention for full credit:** a restart loop never pings the heartbeat, so the alert fires; a pre-deploy config check that fails the deploy (or equivalent); distinct exit codes; a test of the check mode that makes no network calls.

</details>
