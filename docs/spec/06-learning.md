# 06 · Learning plan

Claude Code writes most of the code. The owner's job is to understand all of it well enough to direct it, catch its mistakes, and defend it in an interview. This file defines how that happens. It is binding on Claude Code: the merge gate in section 2 applies to every PR.

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
| 2. Predict | Owner | Write 5 to 10 lines in `docs/learning/predictions/NNN-<topic>.md`: how would I build this, and what could go wrong? No peeking |
| 3. Plan | Claude | Present the plan; compare it with the prediction; name what the prediction missed and what it got right |
| 4. Build | Claude | Tests first, then implementation, in small commits |
| 5. Walkthrough | Claude | Explain the diff file by file: what, why, the main alternative rejected. Define every new term once |
| 6. Quiz | Claude asks, owner answers | Five questions: two "what does this do", two "what breaks if…", one "how would you change it to…". Log questions and answers in `docs/learning/quiz-log.md` |
| 7. Break | Owner | Break one thing on purpose (delete a line, feed bad input) and predict the failure before running it |
| 8. Log | Owner | Three lines in `docs/learning/daily-log.md`: learned, confused by, question for tomorrow |

**Gate (ADR-003):** a PR may merge once CI passes, with its quiz and "What I learned" owed and tracked in `docs/learning/owed.md`. A milestone isn't done, and the next doesn't start, until the owner has scored at least 4 of 5 on every owed quiz and written every "What I learned" in his own words. If the score is lower, Claude re-explains the weak area a different way and asks new questions. Claude must not soften the questions or accept vague answers.

**When time is short,** steps 2 and 7 may be skipped for pure boilerplate (config, Dockerfiles, CI plumbing). Steps 5 and 6 are never skipped.

## 3. Owner-written core

Seven pieces the owner writes by hand, because interviews test writing, not reading. For each, Claude writes the tests and fixtures first, gives hints only when asked, and reviews the result like a staff engineer: correctness, edge cases, naming, performance. Claude does not write the implementation.

| # | Piece | File | Milestone | Skill it builds |
| --- | --- | --- | --- | --- |
| 1 | GTFS time and service-date conversion | `packages/ghostbus_core/service_date.py` | M1 | Time zones, edge cases, pure functions |
| 2 | Schedule expansion | `pipeline/dbt/models/intermediate/int_schedule_expanded.sql` | M1 | Joins, set logic, date handling |
| 3 | Trip matching through the crosswalk | `pipeline/dbt/models/intermediate/int_trip_crosswalk.sql` | M1 (exact), M4 (fuzzy) | Joins across sources, measuring match rates |
| 4 | Outcome classification | `pipeline/dbt/models/gold/fct_trip_outcomes.sql` | M1 (three outcomes), M4 (full decision table) | CASE logic, window functions, CTE structure |
| 5 | One endpoint, end to end | `GET /v1/lines/{line}/reliability`: router, repo, schema, tests | M2 | HTTP, SQL, validation, testing |
| 6 | Commute matching query | `services/detector/matching.py` | M3 | Joins with time logic, idempotent inserts |
| 7 | Cluster bootstrap | `analysis/bootstrap.py` | M6 | Statistics in code, reproducibility |

**Rewrite drill:** one week after each piece merges, rewrite it from a blank file in 45 minutes without looking. If that fails, study it and repeat three days later.

If a milestone is slipping, Claude may write piece 5 or 7, and the owner then does the rewrite drill twice. Pieces 1, 2, 3, 4, and 6 are always owner-written.

## 4. Daily schedule (12 hours, 6 days a week)

| Block | Hours | What |
| --- | --- | --- |
| SQL drills | 1.5 | By hand, from memory. Weeks 1–2: joins, GROUP BY, CTEs. Weeks 3–4: window functions, dedup, gaps and islands. Weeks 5–8: timed mediums |
| DSA in Python | 1.5 | Arrays and hashing → two pointers and sliding window → stacks and binary search → trees → graphs → heaps and intervals. One new pattern every 3 to 4 days; timed from week 5 |
| Project | 6 | The loop in section 2 |
| Fundamentals | 1 | Reading matched to the milestone (section 5) |
| Interview prep and outreach | 1 | Behavioral stories, explaining the project aloud, rider outreach, applications |
| Review | 1 | Yesterday's quiz misses; rewrite drills; flashcards for definitions |

Take the seventh day off. Stop the project block if the quiz score falls: more hours past that point produce code the owner can't explain.

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

Record the scores in `docs/learning/checkpoints.md`. Two weak checkpoints in a row mean the next milestone's P1 items are dropped in favor of consolidation.

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
- Asks for the prediction before presenting a plan
- Refuses to write the seven owner-written pieces, and says why
- Keeps PRs small enough to explain in 15 minutes (under about 400 changed lines, excluding generated files)
- Ends each working session by asking the owner to state, in two sentences, what was built and why
- Flags when the owner's answers show a gap, and proposes a short exercise to close it
