# ADR-022: Quizzes are logged, not gated; an interview-decisions file is the explain-back record

- **Status:** Accepted
- **Date:** 2026-11-15
- **Supersedes:** ADR-003 decision 1 (the explain-back gate at the milestone). ADR-003 decisions 2 to 4 (SLOs, incident log, tools on evidence) stand
- **Evidence:** `docs/learning/owed.md` on 2026-11-15: 17 quizzes and 17 "What I learned" notes owed, none taken; M0 two days past its Nov 12–13 dates

## Context

ADR-003 let PRs merge with their quiz owed, but blocked each milestone until every owed quiz scored 4 of 5. By M0's end that is 17 quizzes, about 85 questions, before M1 can start. The owner wants to finish the project as fast as possible and asked on 2026-11-15 to stop taking quizzes for now.

The quizzes still have value as study material, and the interview is the real test. What the owner needs to defend there is the set of trade-offs, not the answer to every line-level question.

## Decision

1. **Quizzes keep being written and logged.** Every PR still gets five questions with model answers in `docs/learning/quizzes/` and a row in `docs/learning/owed.md`. The owner takes them when he chooses. They do not block a merge or a milestone.
2. **"What I learned" notes are optional** under the same terms.
3. **`docs/learning/interview-decisions.md` is the explain-back record.** Every PR that makes or changes a decision worth defending in an interview adds or updates an entry there: the decision, why, the main alternative rejected, and what would change it. Claude keeps it current; it is part of the definition of done.
4. Unchanged: walkthroughs, the seven owner-written pieces, and the owner's "Why" rewrites on ADRs. Changing those needs its own decision.

## Why

<!-- OWNER: rewrite this paragraph in your own words. -->

Finishing matters more now than proving understanding PR by PR. A gate of 85 questions at the end of M0 would stall M1 for days. Interviews ask about trade-offs, so one file of trade-offs, kept current, is the highest-value study material per minute. The quizzes stay in the repo for whenever there is time.

## Alternatives considered

- **Keep the milestone gate (ADR-003).** Keeps understanding close behind the code, but the backlog already blocks M1.
- **Delete the quizzes and stop writing them.** Saves a little time per PR, but throws away ready-made study material. Writing five questions is cheap next to the PR itself.
- **Gate on the interview-decisions file instead** (owner explains each entry aloud before the milestone closes). A lighter gate, but still a gate; the owner asked for none.

## Consequences

- Code can reach `main`, and milestones can close, before the owner can explain them. The risk moves to interview time, and the interview-decisions file is the mitigation.
- `docs/learning/owed.md` becomes a study backlog, not a blocker.
- The learning spec (section 2, gate paragraph) and `CLAUDE.md` are updated to match.

## Would change if

- The owner asks for the gate back, or a mock interview shows he can't defend entries in the decisions file.
