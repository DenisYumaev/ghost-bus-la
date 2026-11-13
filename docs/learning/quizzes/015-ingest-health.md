# Quiz 015 · PR #17 · Health check and heartbeat

**How to take it:** write your answer under each question first, then open the model answer to compare. When you've finished, tell Claude, who grades your written answers and logs the score in `docs/learning/quiz-log.md`. You need 4 of 5 before M0 closes. A vague answer scores zero.

To reveal an answer: click **Model answer** on GitHub, or open VS Code's preview (`Cmd+Shift+V`) and click it there.

---

## 1. What does this do?

State the `/healthz` rule exactly, including what happens right after startup, and give the response for a service that started 100 s ago, with vehicle positions last succeeding 20 s ago and trip updates never succeeding.

**Your answer:**

>

<details>
<summary>Model answer</summary>

**Rule:** healthy if **every** feed had a successful cut (`written` or `duplicate`) within **three of its intervals**. `network_error` and `spool_error` don't count. Until a feed's first success, the **service start time** stands in, which gives each feed a startup grace period of three of its intervals.

**The example** (vehicle positions 30 s, so the limit is 90 s; trip updates 60 s, so the limit is 180 s):

- Vehicle positions: 20 s since success, under 90, so healthy.
- Trip updates: never succeeded, so measured from start: 100 s, under 180, so healthy *for now*.
- **200 OK**, `status: ok`. If trip updates still hasn't succeeded at 181 s, it becomes **503**, `status: unhealthy`, with `trip_updates.healthy: false` in the per-feed detail.

**Must mention for full credit:** every feed, a success within 3 intervals, failures not counting; start time as the stand-in (grace); the correct verdict for the example (200, and why trip updates is still within grace).

</details>

---

## 2. What does this do?

The spec originally said to ping the heartbeat "after each successful cycle of the 30 s feed." What did this PR change, and why does it matter for the trip-updates stream?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**Change:** ingest pings after each successful cut of the **fastest** feed, but **only while every feed is healthy** (the same rule as `/healthz`).

**Why:** trip updates is the critical stream. It carries the announced cancellations that drive alerts and the advance-notice gate. Under the original wording, if trip updates died (a server-side change, a parser crash, a stuck connection) while vehicle positions kept working, the heartbeat would keep saying "all good." Nobody would be alerted, and cancellation history would be lost silently. Now a failing trip-updates stream stops the pings after its 3-interval grace (180 s), and Healthchecks alerts within its grace window.

The test `test_no_heartbeat_while_a_feed_is_failing` proves it. Making the ping unconditional was planted in this PR, and that test failed.

**Must mention for full credit:** ping only while every feed is healthy (not just vehicle positions succeeding); a dead trip-updates stream would otherwise go unnoticed while the critical data is lost; the test that guards it.

</details>

---

## 3. What breaks if…

The heartbeat URL were logged at startup (for example `log_event("heartbeat_enabled", url=url)`). Logs are only on the VM. Why is that still a problem?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The ping URL **is the credential**: anyone who has it can send pings. Logging it puts it in places that aren't protected like Parameter Store:

- Docker's log files on the VM, readable by anyone who gets a shell, kept through rotation, and possibly shipped to a hosted log store later (infra spec, section 7).
- Screenshots or copy-pastes of logs when debugging, and chat messages asking for help.

With the URL, someone (or a misconfigured script) could **send "all good" pings while ingest is actually down**, silencing the one alert that works when the VM is dead. Or they could ping "fail" and cause false alarms.

So the URL is treated as a secret: SecureString in SSM, never logged (the test `test_a_failed_ping_never_raises` asserts it isn't in the log output), and the owner stores it himself rather than pasting it into chat (hard rule 9's spirit).

**Must mention for full credit:** the URL works as a credential; logs spread it to unprotected places; misuse means false "healthy" pings that hide a real outage (or false alarms); keep it in SSM and out of logs.

</details>

---

## 4. What breaks if…

`resolve_heartbeat_url` raised an exception when the SSM parameter is missing, instead of logging `heartbeat_disabled` and returning `None`. What would happen on the first deploy if the owner hadn't stored the parameter yet?

**Your answer:**

>

<details>
<summary>Model answer</summary>

`main()` would crash before the streams start. The container exits, Docker restarts it, it crashes again: a **restart loop with zero archiving**. Every minute of that loop is cancellation history lost for good, and since there's no heartbeat, nothing alerts. A missing *monitoring* secret would have stopped the *thing being monitored*.

That inverts the priorities of hard rule 3, "the archive comes first": ingest depends only on network, disk, and S3. The heartbeat is a nice-to-have relative to archiving. So a missing or invalid URL **disables only the heartbeat**, logs `heartbeat_disabled` (visible in `docker logs`), and archiving proceeds.

The deploy PR should still check that the parameter exists, so "heartbeat disabled" is a deliberate state and never a surprise.

**Must mention for full credit:** a crash before streaming leads to a restart loop and no archive; the heartbeat is secondary to archiving (hard rule 3); disable with a log line instead; the deploy-time check as a complement.

</details>

---

## 5. How would you change it to…

Healthchecks also accepts pings to `<url>/fail` (alert immediately) and `<url>/start`. How would you use `/fail` so the owner hears about a crashed stream faster than the 3-minute silence, and what's the risk?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**Change:** when the service detects a definite failure, ping `<url>/fail` right away, best effort with a short timeout:

- `stream_crashed` or `uploader_crashed` in `run_service`, just before exiting with code 1;
- or when `/healthz` turns from healthy to unhealthy (a transition, not every check), meaning a feed has been failing for 3 intervals.

Healthchecks marks the check down and alerts immediately, without waiting for Period plus Grace. The next successful ping marks it up again.

**Test first:** with `MockTransport`, assert a crashed stream produces exactly one request to `…/fail` before exit, and that a healthy run never hits `/fail`.

**Risks:**

- **Flapping:** a feed hovering at the 3-interval edge could alternate fail and success pings, sending alert storms. Mitigate by only sending `/fail` on the healthy-to-unhealthy transition, and only once per incident.
- **A crash during the ping itself:** keep it best effort with a timeout, so a slow Healthchecks never delays the restart.
- A crash-*looping* container would `/fail` every few seconds. Rate-limit it, or rely on the silence instead.

**Must mention for full credit:** `/fail` on definite failures (crash, or the healthy-to-unhealthy transition); best effort with a timeout; flapping or alert storms as the main risk, with a mitigation (send on transitions only); a test asserting the fail ping.

</details>
