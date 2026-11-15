# Quiz 018 · PR #21 · The GTFS schedule download

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

Walk through one call to `GtfsDownloader.download_once` when Metro has just published a new schedule. What is stored, where, and under what name?

**Your answer:**

>

<details>
<summary>Model answer</summary>

1. It streams the ZIP from GitLab, with 120 s as a limit on the whole request, reading at most 64 MB (refused up front if `Content-Length` says more).
2. In a worker thread, so the streams' event loop isn't blocked, it checks the response: status 200 and actually a ZIP (`zipfile.is_zipfile`).
3. It hashes the exact bytes (SHA-256). These differ from the last stored hash, which is kept in `gtfs_static/last_sha256` so it survives restarts, so `Spool.write_file` writes them atomically (temp file, `fsync`, rename, directory `fsync`) as `gtfs_static/<fetch time>_<sha16>.zip`.
4. It logs a `fetch` line with `outcome: written`, the HTTP status, latency, size and hash.
5. Later, the uploader checks the file's hash against its name and stores it at `bronze/gtfs_static/dt=<UTC date>/<sha16>.zip` with `If-None-Match: *`.

The ZIP is never unzipped or re-zipped: bronze keeps raw bytes (ADR-001 decision 2).

</details>

## 2. What does this do?

Why does `next_daily_run` build the next run from the local calendar date instead of adding 24 hours to the last run?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Because two days a year in Los Angeles are 23 or 25 hours long. Adding 24 hours after a daylight-saving change would move the run to 02:00 or 04:00 local and keep it there. Taking tomorrow's date and setting 03:00 in `America/Los_Angeles` keeps it at 03:00 local every day. The tests cover both the spring-forward and the fall-back dates.

</details>

## 3. What breaks if…

…GitLab serves a maintenance page with status 200, and the downloader doesn't check that the body is a ZIP?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The HTML page gets a new hash, so it's stored as a new **schedule version** in bronze, where it can never be deleted (the bucket denies deletes). In M1 the pipeline treats every new hash as a version, tries to extract `routes.txt` from it, and fails. Worse, it could become "the version in force" for that day and break trip matching. The ZIP check rejects it as `http_error`, logs its hash, and retries with backoff.

</details>

## 4. What breaks if…

…every 4xx response were retried with the normal backoff, and Metro moved the file (a permanent 404)?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The backoff caps at 60 s, so ingest would request the missing file about once a minute, forever: about 1,440 pointless requests a day against someone else's server. A 404 won't fix itself. So `should_retry` waits for the next daily slot on any 4xx except 429 (rate limited, where backing off is the right response). Even retryable failures stop after 10 in a row and wait for the daily slot. The daily `http_error` line in the fetch log is the signal to fix the URL.

</details>

## 5. How would you change it to…

…catch a schedule that GitLab updated at 10:00, instead of waiting until 03:00 the next day?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Check more often, but cheaply. Send a conditional request (`If-None-Match` with the last `ETag`, or `If-Modified-Since`) every hour or so. A `304 Not Modified` costs a few hundred bytes, and only a `200` downloads the 22 MB. That needs a new `not_modified` outcome in the fetch log and a test for it. It's worth doing only if same-day freshness matters, which it doesn't yet: schedules change at service changes and weekly calendar updates, and the pipeline resolves the version in force per service date.

</details>
