# ADR-003: Operating standards: explain-back merge gate, SLOs, incident log, tools on evidence

- **Status:** Proposed
- **Date:** 2026-11-12
- **Evidence:** `docs/spec/06-learning.md` (the loop and merge gate); `docs/spec/05-infra-ops.md` sections 8 (SLOs) and 14 (incidents); ADR-002 (the project's purpose)

## Context

One person owns this system, and a coding agent writes most of its code. That creates two risks. Code can merge faster than the owner understands it, so the project stops being his to defend in an interview. And "it works" can stay an unmeasured claim. Four standards address these risks, and later decisions refer back to them.

## Decision

1. **Explain-back merge gate.** A PR merges only when the owner has (a) scored at least 4 of 5 on its quiz, with questions recorded in `docs/learning/quizzes/` and scores in `docs/learning/quiz-log.md`, and (b) written the PR's "What I learned" section in his own words. Claude does not soften questions or accept vague answers. A failed quiz means a different explanation and new questions, not a lower bar.
   - **Predictions** (learning spec, loop step 2) are encouraged, but the owner may skip them for any PR. Since 2026-11-12 they are paused at the owner's request so the build can move faster. A skipped prediction is noted in the PR description. The quiz and "What I learned" are never skipped.
   - A PR may be built and opened before its quiz is taken. Unmerged PRs then stack, and merging waits for the quiz.
2. **SLOs with an error budget.** Reliability targets are the ones in `docs/spec/05-infra-ops.md` section 8, measured from the system's own records (fetch log, outbox, publish runs, an external uptime monitor). The capture SLO is 99.5% of minutes per feed per month, which allows 216 minutes of budget. If a month's budget is spent, feature work stops until the cause is fixed and written up.
3. **Incident log.** Anything that loses data, sends a wrong or duplicate alert, takes the site down for more than 5 minutes, breaches an SLO, or requires a manual action on production data gets a blameless write-up in `docs/incidents/YYYY-MM-DD-slug.md`: what happened, impact, timeline, cause, what changed. The leaked AWS access key of 2026-11-10 is the first entry.
4. **New tools are adopted on evidence.** A dependency, service, or tool outside the stack list in `CLAUDE.md` needs an ADR that names the measured problem it solves and the simpler option it beat. Small libraries that are the standard way to use a tool already in the stack (for example, boto3 as the client for S3) are recorded in the ADR that first needs them rather than getting an ADR of their own.

## Why

<!-- OWNER: rewrite this paragraph in your own words before this PR merges (SPEC.md section 5). -->

When an agent writes the code, typing stops being the bottleneck and understanding becomes it. A merge gate the owner must pass keeps every file explainable, which is the whole point of a portfolio project. SLOs turn "it runs" into a number someone can check, and the error budget makes the trade-off between features and reliability a rule instead of a mood. Incident write-ups turn failures into evidence and into interview stories. Requiring evidence for new tools keeps the system small enough for one person to run and explain.

## Alternatives considered

- **No gate; read the diff and merge.** Fastest, but the code stops being the owner's, and the first deep-dive interview exposes it.
- **Predictions mandatory on every PR**, as the learning spec first said. Better for learning, but slower. The owner chose speed here, and the quiz still enforces understanding before merge.
- **A 99.9% capture target.** Unrealistic on one VM that deploys in place: 43 minutes a month leaves no room for one bad deploy.
- **Adopt tools freely, as they seem useful.** Each one adds operations, cost, and something to explain. Kafka, Redis, and Kubernetes are named non-goals for this reason (`docs/SPEC.md` section 5).

## Consequences

- PRs can wait on quizzes. Stacked branches need rebasing when an earlier PR merges.
- `docs/learning/` becomes part of the repo's evidence: quizzes, scores, and the daily log show how understanding grew.
- An SLO breach or incident is visible work with a written result, not something quietly fixed.
- This ADR changes the learning spec's rule that predictions may be skipped only for boilerplate (ADRs take precedence over component specs).

## Would change if

- Quiz scores fall for two weekly checkpoints in a row: predictions come back first (learning spec, section 6).
- The capture SLO proves unreachable for reasons this system controls, which calls for a new ADR with a measured target.
