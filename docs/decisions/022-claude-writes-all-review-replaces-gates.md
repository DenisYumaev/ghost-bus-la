# ADR-022: Claude writes all code and ADRs; quizzes are logged, not gated; quality comes from tests and independent review

- **Status:** Accepted
- **Date:** 2026-11-15
- **Supersedes:** ADR-003 decision 1 (the explain-back gate). The learning spec's owner-written core (section 3), its rewrite drill, and the rule that the owner rewrites each ADR's "Why". ADR-003 decisions 2 to 4 (SLOs, incident log, tools on evidence) stand
- **Evidence:** `docs/learning/owed.md` on 2026-11-15: 17 quizzes and 17 "What I learned" notes owed, none taken; M0 two days past its Nov 12–13 dates

## Context

The learning plan put the owner on the critical path in four places: a quiz gate at each milestone (17 quizzes owed by M0's end), seven pieces of code he writes by hand (five of them in M1), a "Why" rewrite before each ADR is accepted, and a live walkthrough of every PR. On 2026-11-15 the owner asked to finish the project quickly without lowering quality, and for Claude to write all of it.

Those four steps did two jobs: teaching the owner, and giving the code a second reader. This ADR drops the first job's gates and replaces the second job with checks that don't need the owner.

## Decision

1. **Quizzes keep being written and logged.** Every PR still gets five questions with model answers in `docs/learning/quizzes/` and a row in `docs/learning/owed.md`. The owner takes them when he chooses. They block no merge and no milestone. "What I learned" notes are optional on the same terms.
2. **Claude writes the seven formerly owner-written pieces** (learning spec, section 3), held to a higher test bar because they carry the project's correctness:
   - property-based tests (Hypothesis) for pure logic, such as service-date conversion and the bootstrap;
   - hand-checked fixture cases for every SQL piece, including the edge cases the specs name (25:10 trips, the daylight-saving change, schedule-version changes, unmatched trips);
   - for dbt models, schema tests on grain and uniqueness.
3. **Every PR gets an independent review before merge**, by a reviewer subagent that sees the diff and the spec but not Claude's reasoning: `reviewer` for everything, plus `sql-reviewer` for SQL and dbt. Findings are fixed or answered in the PR description.
4. **Claude writes each ADR's "Why"**, and ADRs are accepted on their evidence (for example, `VERIFY` results), not on an owner rewrite.
5. **The walkthrough is written, not live:** a "Walkthrough" section in the PR description covering what each file does, why, and the main alternative rejected. It's there for the owner to read when he wants.
6. **`docs/learning/interview-decisions.md` is the explain-back record.** Every PR that makes or changes a decision worth defending adds or updates an entry there. It is part of the definition of done.

Unchanged: tests first, CI green, PRs of about 400 changed lines, the hard rules in `CLAUDE.md`, and owner approval of every `terraform apply`.

## Why

Finishing matters more now than proving understanding PR by PR. Gates on 17 quizzes, five hand-written M1 pieces, and ADR rewrites would stall M1 for days. Their quality job, a second reader for the code, is done better and faster by stronger tests and an independent reviewer that doesn't share the author's assumptions. Interviews ask about trade-offs, so one file of trade-offs kept current is the most useful study material per minute, and the quizzes stay in the repo for whenever there's time.

## Alternatives considered

- **Keep the learning plan as written** (ADR-003 and the learning spec). Strong for learning, but the backlog already blocks M1.
- **Drop the gates but keep the owner-written pieces.** They're the best interview practice, but five of them sit on M1's critical path, and the owner chose speed.
- **Drop the gates without replacing the second reader.** Fastest, but code reviewed only by its author is how subtle bugs (grain errors, time-zone mistakes) reach production.

## Consequences

- The owner may not be able to explain code that he didn't write and hasn't studied. The risk moves to interview time; `interview-decisions.md`, the written walkthroughs, and the logged quizzes are the mitigation.
- "I wrote the core logic by hand" is no longer true and must not be claimed (CLAUDE.md hard rule 11).
- ADR-003 and ADR-004 are accepted in the PR that adds this ADR. ADR-021 stays Proposed until the measured day.
- The learning spec, `docs/SPEC.md`, the ADR index, and `CLAUDE.md` are updated to match.

## Would change if

- The owner asks for any part back, or a mock interview shows he can't defend entries in the decisions file.
- Independent review keeps missing bugs that reach `main`. Then add a second reviewer or bring back an owner review for the riskiest pieces.
