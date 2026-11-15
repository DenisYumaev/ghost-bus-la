# 06 · Learning plan

Claude Code writes most of the code. The owner's job is to understand all of it well enough to direct it, catch its mistakes, and defend it in an interview. This file defines how that happens. Since ADR-022 (2026-11-15) nothing in it gates a merge or a milestone. Claude writes all code; steps marked optional below are practice the owner does when he chooses.

## 1. The standard

By M8 the owner can, without notes:

- Draw the architecture and trace a cancellation from Metro's feed to a rider's inbox
- Explain every file in the repo: what it does, why it exists, what breaks without it
- Write a medium SQL problem in 20 minutes and a medium DSA problem in 30
- Answer the 30 questions in section 7
- Tell five behavioral stories drawn from real events in this project

## 2. The loop (every PR)

| Step | Who | What |
| --- | --- | --- |
| 1. Brief | Claude | State the goal, the spec section, and the constraints in under 10 lines |
| 2. Predict (optional, ADR-022) | Owner | Write 5 to 10 lines in `docs/learning/predictions/NNN-<topic>.md`: how would I build this, and what could go wrong? No peeking |
| 3. Plan | Claude | Present the plan; compare it with the prediction; name what the prediction missed and what it got right |
| 4. Build | Claude | Tests first, then implementation, in small commits |
| 5. Walkthrough | Claude | Written in the PR description (ADR-022): each file, what, why, the main alternative rejected. Define every new term once |
| 6. Quiz | Claude records | Five questions with model answers in `docs/learning/quizzes/`: two "what does this do", two "what breaks if…", one "how would you change it to…". The owner takes them when he chooses; scores go in `docs/learning/quiz-log.md` |
| 7. Break (optional) | Owner | Break one thing on purpose (delete a line, feed bad input) and predict the failure before running it |
| 8. Log (optional) | Owner | Three lines in `docs/learning/daily-log.md`: learned, confused by, question for tomorrow |

**Gate (ADR-022, superseding ADR-003's gate):** there is no quiz gate. Claude still writes each PR's quiz into `docs/learning/quizzes/` and lists it in `docs/learning/owed.md`; the owner takes quizzes when he chooses. Every PR that makes or changes a decision worth defending updates `docs/learning/interview-decisions.md`.

**When time is short,** steps 2 and 7 may be skipped for pure boilerplate (config, Dockerfiles, CI plumbing). Step 5 is never skipped; step 6 is recorded, not taken (ADR-022).

## 3. Owner-written core (superseded by ADR-022)

**Since 2026-11-15, Claude writes all seven pieces**, with property-based tests, hand-checked fixtures, and an independent reviewer pass (ADR-022). The rewrite drill is dropped. The table stays as the list of the project's most important code, worth studying for interviews.

~~Seven pieces the owner writes by hand.~~ Superseded: Claude writes them (see the note above).

| # | Piece | File | Milestone | Skill it builds |
| --- | --- | --- | --- | --- |
| 1 | GTFS time and service-date conversion | `packages/ghostbus_core/src/ghostbus_core/service_date.py` | M1 | Time zones, edge cases, pure functions |
| 2 | Schedule expansion | `pipeline/dbt/models/intermediate/int_schedule_expanded.sql` | M1 | Joins, set logic, date handling |
| 3 | Trip matching through the crosswalk | `pipeline/dbt/models/intermediate/int_trip_crosswalk.sql` | M1 (exact), M4 (fuzzy) | Joins across sources, measuring match rates |
| 4 | Outcome classification | `pipeline/dbt/models/gold/fct_trip_outcomes.sql` | M1 (three outcomes), M4 (full decision table) | CASE logic, window functions, CTE structure |
| 5 | One endpoint, end to end | `GET /v1/lines/{line}/reliability`: router, repo, schema, tests | M2 | HTTP, SQL, validation, testing |
| 6 | Commute matching query | `services/detector/matching.py` | M3 | Joins with time logic, idempotent inserts |
| 7 | Cluster bootstrap | `analysis/bootstrap.py` | M6 | Statistics in code, reproducibility |

~~Rewrite drill~~ and the owner-written rule: dropped by ADR-022. Rewriting a piece from a blank file is still good interview practice if there's time.

## 4. Daily schedule (12 hours, 6 days a week)

| Block | Hours | What |
| --- | --- | --- |
| SQL drills | 1.5 | By hand, from memory. Weeks 1–2: joins, GROUP BY, CTEs. Weeks 3–4: window functions, dedup, gaps and islands. Weeks 5–8: timed mediums |
| DSA in Python | 1.5 | Arrays and hashing → two pointers and sliding window → stacks and binary search → trees → graphs → heaps and intervals. One new pattern every 3 to 4 days; timed from week 5 |
| Project | 6 | The loop in section 2 |
| Fundamentals | 1 | Reading matched to the milestone (section 5) |
| Interview prep and outreach | 1 | Behavioral stories, explaining the project aloud, rider outreach, applications |
| Review | 1 | Optional: quiz misses; `interview-decisions.md` aloud; flashcards for definitions |

Take the seventh day off. (The old rule to stop the project block when quiz scores fall is dropped, ADR-022.)

## 5. Concept map: what to learn when

| Milestone | Concepts | Read |
| --- | --- | --- |
| M0 | HTTP basics, idempotency, atomic file writes, object storage, IAM roles | AWS docs on S3 consistency and IAM roles; *Designing Data-Intensive Applications* (DDIA) ch. 1 |
| M1 | GTFS and GTFS-realtime, columnar storage, partitioning, dimensional modeling, grain | GTFS reference; DDIA ch. 3; Kimball, *The Data Warehouse Toolkit*, ch. 1–3 |
| M2 | REST design, HTTP caching and ETags, indexes and query plans, connection pools, DNS and TLS | Postgres docs: indexes, `EXPLAIN`; MDN: HTTP caching |
| M3 | Transactions and isolation, the outbox pattern, at-least-once delivery, idempotency keys, sessions and cookies, CSRF | DDIA ch. 7 and 11; OWASP cheat sheets: session management, CSRF |
| M4 | Orchestration, backfills, slowly changing dimensions, schema evolution | Airflow core concepts; Kimball on SCD Type 2; DDIA ch. 4 and 10 |
| M5 | SLOs and error budgets, load testing, percentiles, caching strategy, threat modeling | Google SRE book: SLO chapter; OWASP Top 10 |
| M6 | Bootstrap methods, clustered data, precision and recall, communicating uncertainty | A bootstrap chapter from any applied statistics text |
| M7–M8 | System design at larger scale: queues, replicas, sharding, warehouses | DDIA ch. 5 and 6 |

Read when the project reaches the problem, not before. Each reading ends with three sentences in the daily log: what it says, where it shows up in this project, what I'd ask the author.

## 6. Weekly checkpoints

Every seventh project day, 60 minutes, recorded:

1. **Whiteboard:** draw the current system from memory; compare with the repo.
2. **Explain a file chosen at random** by Claude, line by line.
3. **Five questions** from section 7, cold.
4. **One timed SQL problem and one timed DSA problem.**
5. **Decide:** what was weakest; which block gets an extra hour next week.

Record the scores in `docs/learning/checkpoints.md`. Checkpoints are optional practice and gate nothing (ADR-022).

## 7. Question bank

**System and design**

1. Walk me through what happens when Metro posts a cancellation, to the rider's inbox.
2. Why are there two paths, hot and batch? What would go wrong with one?
3. Why Postgres for serving and DuckDB for the pipeline? What would you use at 100 times the data?
4. The alert worker crashes right after the email provider accepts a message. What does the rider see, and why?
5. What exactly does "at-least-once" mean in your system, and where does idempotency come from?
6. Why `FOR UPDATE SKIP LOCKED`? What happens without `SKIP LOCKED`?
7. How do you deploy without losing data from the archive?
8. Your API has to serve 100 times the traffic. What breaks first, and what do you change, in order?
9. Why one VM and not Kubernetes or serverless? When would that decision flip?
10. How would you add a second city?

**API and security**

11. Why email links instead of passwords? What are the weaknesses?
12. Why is verification a POST from a page and not a GET link?
13. How do sessions work here? Why not JWTs?
14. How is CSRF prevented? How do you prevent one user from reading another's commutes?
15. How does caching work across the browser, the API, and the database? How do you avoid serving stale data after a publish?
16. Why cursor pagination instead of offset?
17. An endpoint is slow. Show me how you find out why.

**Data**

18. How do you tell a canceled trip from a feed outage, or from a bus with a broken GPS unit?
19. Where does a trip scheduled at 25:10 go, and what happens on the day the clocks change?
20. Metro changed every trip ID overnight. Why are last month's numbers still right?
21. What happens if `ingest` writes the same snapshot twice, or the pipeline runs twice?
22. You fixed a bug in trip matching. How do you recompute history, and how long does it take?
23. Why is a Wilson interval wrong here, and what does the cluster bootstrap fix?
24. Your rate differs from Metro's report by 3 points on one line. Debug it out loud.
25. Why does the API never see a half-loaded table?

**Operations and product**

26. What are your SLOs, and why those numbers? What happened the last time one was breached?
27. Tell me about an incident. What did you change afterwards?
28. How do you know riders find the alerts useful? What did you change because of feedback?
29. What did you choose not to build, and why?
30. What would you do differently if you started over?

## 8. Behavioral stories

Write each as situation, action, result, and what changed afterwards, in 90 seconds. Keep them in `docs/learning/stories.md`.

| Theme | Source in this project |
| --- | --- |
| A mistake and how you handled it | The leaked AWS key: caught, rotated in minutes, new habits |
| Ownership | Running a production system alone; a specific on-call moment |
| Changing direction on evidence | Moving from a data pipeline to a rider product; the M1 advance-notice gate |
| Disagreeing with data | Reconciling against Metro's report |
| Listening to users | A change made after rider feedback |
| Scoping under pressure | What was cut, and why, when a milestone slipped |

## 9. What Claude Code does differently because of this file

- Explains as it goes; defines each new term once; never assumes background the owner hasn't shown
- Writes the seven core pieces to the ADR-022 test bar and gets each one independently reviewed
- Keeps PRs small enough to explain in 15 minutes (under about 400 changed lines, excluding generated files)
- Ends each working session by asking the owner to state, in two sentences, what was built and why
- Flags when the owner's answers show a gap, and proposes a short exercise to close it
