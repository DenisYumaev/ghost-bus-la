# Owed learning work

Everything the owner still has to do for each PR. The owner deferred these on 2026-11-12 so the build could keep moving. Claude adds a row with every new PR and ticks items off when they're done.

**How to clear an item**

- **Quiz:** open the file from its link, write your answers under each question, tell Claude, and get graded (4 of 5 to pass).
- **What I learned:** write 3 to 5 sentences in the space below, in your own words. Claude copies it into the PR description.
- **Why rewrite:** edit the ADR's "Why" section directly and delete its `OWNER` marker line.

Quizzes live on their PR's branch until it merges, so use the GitHub links. They work whichever branch you have checked out.

## Status

| PR | Topic | Quiz | What I learned | Why rewrite | Applied to AWS |
| --- | --- | --- | --- | --- | --- |
| [#1](https://github.com/DenisYumaev/ghost-bus-la/pull/1) | ADR-021, realtime source | [ ] [001](https://github.com/DenisYumaev/ghost-bus-la/blob/docs/adr-021/docs/learning/quizzes/001-adr-021.md) | [ ] | [x] ADR-021 | n/a |
| [#2](https://github.com/DenisYumaev/ghost-bus-la/pull/2) | Repo scaffold | [ ] [002](https://github.com/DenisYumaev/ghost-bus-la/blob/chore/scaffold/docs/learning/quizzes/002-scaffold.md) | [ ] | n/a | n/a |
| [#3](https://github.com/DenisYumaev/ghost-bus-la/pull/3) | ADR-003 and ADR-004 | [ ] [003](https://github.com/DenisYumaev/ghost-bus-la/blob/docs/adr-003-004/docs/learning/quizzes/003-adr-003-004.md) | [ ] | [ ] ADR-003, [ ] ADR-004 | n/a |
| [#4](https://github.com/DenisYumaev/ghost-bus-la/pull/4) | Terraform state bucket | [ ] [004](https://github.com/DenisYumaev/ghost-bus-la/blob/infra/bootstrap/docs/learning/quizzes/004-infra-bootstrap.md) | [ ] | n/a | Yes, 2026-11-12 |
| [#5](https://github.com/DenisYumaev/ghost-bus-la/pull/5) | Data bucket import, policy, budget | [ ] [005](https://github.com/DenisYumaev/ghost-bus-la/blob/infra/data-bucket/docs/learning/quizzes/005-infra-data-bucket.md) | [ ] | n/a | Yes, 2026-11-12 |

**Suggested order:** 002 and 004 first, because PR #4 is already live in AWS and can't merge before PR #2. Then 005 once it's applied. Then 001 and 003.

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
