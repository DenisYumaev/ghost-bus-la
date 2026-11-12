# ADR-003: Operating standards: explain-back merge gate, SLOs, incident log, tools on evidence

- **Status:** Proposed
- **Date:** 2026-11-12
- **Evidence:** `docs/spec/06-learning.md` (the loop and merge gate); `docs/spec/05-infra-ops.md` sections 8 (SLOs) and 14 (incidents); ADR-002 (the project's purpose)

## Context

One person owns this system, and a coding agent writes most of its code. That creates two risks. Code can merge faster than the owner understands it, so the project stops being his to defend in an interview. And "it works" can stay an unmeasured claim. Four standards address these risks, and later decisions refer back to them.

## Decision

1. **Explain-back gate, enforced at the milestone.** Every PR gets a quiz (five questions, recorded in `docs/learning/quizzes/`) and a "What I learned" section the owner writes in his own words. A PR may **merge once its CI checks pass**, with its quiz and "What I learned" still owed. Owed work is tracked in `docs/learning/owed.md`. A milestone isn't done, and the next one doesn't start, until every owed quiz for it is passed (at least 4 of 5, scored in `docs/learning/quiz-log.md`) and every "What I learned" is written. Claude does not soften questions or accept vague answers. A failed quiz means a different explanation and new questions, not a lower bar.
   - **Predictions** (learning spec, loop step 2) are encouraged, but the owner may skip them for any PR. Since 2026-11-12 they are paused at the owner's request so the build can move faster. A skipped prediction is noted in the PR description. The quiz and "What I learned" are never skipped.
   - The gate moved from each merge to each milestone on 2026-11-12, at the owner's request: waiting on quizzes stacked PRs six deep and left `main` empty.
2. **SLOs with an error budget.** Reliability targets are the ones in `docs/spec/05-infra-ops.md` section 8, measured from the system's own records (fetch log, outbox, publish runs, an external uptime monitor). The capture SLO is 99.5% of minutes per feed per month, which allows 216 minutes of budget. If a month's budget is spent, feature work stops until the cause is fixed and written up.
3. **Incident log.** Anything that loses data, sends a wrong or duplicate alert, takes the site down for more than 5 minutes, breaches an SLO, or requires a manual action on production data gets a blameless write-up in `docs/incidents/YYYY-MM-DD-slug.md`: what happened, impact, timeline, cause, what changed. The leaked AWS access key of 2026-11-10 is the first entry.
4. **New tools are adopted on evidence.** A dependency, service, or tool outside the stack list in `CLAUDE.md` needs an ADR that names the measured problem it solves and the simpler option it beat. Small libraries that are the standard way to use a tool already in the stack (for example, boto3 as the client for S3) are recorded in the ADR that first needs them rather than getting an ADR of their own.

## Why

<!-- OWNER: rewrite this paragraph in your own words before this PR merges (SPEC.md section 5). -->

When an agent writes the code, typing stops being the bottleneck and understanding becomes it. A merge gate the owner must pass keeps every file explainable, which is the whole point of a portfolio project. SLOs turn "it runs" into a number someone can check, and the error budget makes the trade-off between features and reliability a rule instead of a mood. Incident write-ups turn failures into evidence and into interview stories. Requiring evidence for new tools keeps the system small enough for one person to run and explain.

## Alternatives considered

- **No gate; read the diff and merge.** Fastest, but the code stops being the owner's, and the first deep-dive interview exposes it.
- **Quiz before every merge**, the original rule. It keeps understanding in step with the code, but with the owner's quizzes deferred it stacks PRs on top of each other, and every fix low in the stack must be carried up through the branches above it. Enforcing at the milestone keeps the requirement and lets work flow.
- **Predictions mandatory on every PR**, as the learning spec first said. Better for learning, but slower. The owner chose speed here, and the quiz still enforces understanding before merge.
- **A 99.9% capture target.** Unrealistic on one VM that deploys in place: 43 minutes a month leaves no room for one bad deploy.
- **Adopt tools freely, as they seem useful.** Each one adds operations, cost, and something to explain. Kafka, Redis, and Kubernetes are named non-goals for this reason (`docs/SPEC.md` section 5).

## Consequences

- Code can reach `main` before the owner can explain it. The milestone gate bounds that gap to one milestone, and `docs/learning/owed.md` keeps it visible.
- `docs/learning/` becomes part of the repo's evidence: quizzes, scores, and the daily log show how understanding grew.
- An SLO breach or incident is visible work with a written result, not something quietly fixed.
- This ADR changes two learning-spec rules: predictions may be skipped only for boilerplate, and a PR merges only after its quiz. Both the learning spec and `CLAUDE.md` are updated to match.

## Would change if

- Quiz scores fall for two weekly checkpoints in a row, or owed work piles past one milestone: the per-merge quiz gate and predictions come back (learning spec, section 6).
- The capture SLO proves unreachable for reasons this system controls, which calls for a new ADR with a measured target.
