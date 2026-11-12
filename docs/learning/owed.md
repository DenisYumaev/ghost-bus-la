# Owed learning work

Everything the owner still has to do for each PR. The owner deferred these on 2026-11-12 so the build could keep moving. Claude adds a row with every new PR and ticks items off when they're done.

**How to clear an item**

- **Quiz:** open the file from its link, write your answers under each question, tell Claude, and get graded (4 of 5 to pass).
- **What I learned:** write 3 to 5 sentences in the space below, in your own words. Claude copies it into the PR description.
- **Why rewrite:** edit the ADR's "Why" section directly and delete its `OWNER` marker line.

All quizzes are in `docs/learning/quizzes/` on `main`. PRs merge with their quiz owed; everything here is due before the milestone closes (ADR-003).

## Status

| PR | Topic | Quiz | What I learned | Why rewrite | Applied to AWS |
| --- | --- | --- | --- | --- | --- |
| [#1](https://github.com/DenisYumaev/ghost-bus-la/pull/1) | ADR-021, realtime source | [ ] [001](quizzes/001-adr-021.md) | [ ] | [x] ADR-021 | n/a |
| [#2](https://github.com/DenisYumaev/ghost-bus-la/pull/2) | Repo scaffold | [ ] [002](quizzes/002-scaffold.md) | [ ] | n/a | n/a |
| [#3](https://github.com/DenisYumaev/ghost-bus-la/pull/3) | ADR-003 and ADR-004 | [ ] [003](quizzes/003-adr-003-004.md) | [ ] | [ ] ADR-003, [ ] ADR-004 | n/a |
| [#4](https://github.com/DenisYumaev/ghost-bus-la/pull/4) | Terraform state bucket | [ ] [004](quizzes/004-infra-bootstrap.md) | [ ] | n/a | Yes, 2026-11-12 |
| [#5](https://github.com/DenisYumaev/ghost-bus-la/pull/5) | Data bucket import, policy, budget | [ ] [005](quizzes/005-infra-data-bucket.md) | [ ] | n/a | Yes, 2026-11-12 |
| [#7](https://github.com/DenisYumaev/ghost-bus-la/pull/7) | VM, role, recovery alarms | [ ] [006](quizzes/006-infra-vm.md) | [ ] | n/a | Not yet |

**Suggested order:** 004, 005, and 006 first, because they describe what is live in AWS right now. Then 002, 001, and 003.

## What I learned (drafts)

### PR #1 · ADR-021

>

### PR #2 · Scaffold

>

### PR #3 · ADR-003 and ADR-004

>

### PR #4 · State bucket

>

### PR #5 · Data bucket

>

### PR #7 · VM

>
