# Start here

This folder is a clean starting point for the **Ghost Bus LA** repo. It doesn't build on the scrapped `la-ghost-bus` repo.

## What's in it

| File | What it is |
| --- | --- |
| `CLAUDE.md` | Rules Claude Code reads automatically at the start of every session |
| `docs/SPEC.md` | Master spec: resume targets, product, architecture, decisions, milestones |
| `docs/spec/01` … `06` | Component specs: pipeline, API, alerts, web, infrastructure, learning plan |
| `docs/decisions/001`, `002` | Accepted decision records: ingestion, and the product direction |
| `docs/research/day1-probe.md` | What Metro's data sources actually do, tested live on Nov 11. Already done; nothing to run |

## 1. Make the new project folder

```bash
cd ~/Documents/Projects
unzip -o ghost-bus-kit-v2.zip
mv ghost-bus-kit-v2 ghost-bus-la
cd ghost-bus-la
```

Create an empty GitHub repo named `ghost-bus-la` (no README, no license). Claude Code will run `git init` and connect it.

## 2. Finish the account checklist

Skip what is already done.

- [ ] Root account has MFA
- [ ] The exposed access key is deleted, and `aws sts get-caller-identity` works with the new one
- [ ] Homebrew, uv, Python 3.12, Docker, Terraform, git, and Node are installed

## 3. The old repo and its AWS resources

The scrapped repo's Terraform created two things in your AWS account: a data bucket and a $40 budget. Its state file is at `la-ghost-bus/infra/terraform.tfstate`.

- **Don't delete the `la-ghost-bus` folder yet.** That state file is the only record Terraform has of those resources.
- M0 tells Claude Code to either import them into the new repo's Terraform or destroy them. Either way you review the plan first.
- After that, archive or delete the old GitHub repo, whichever you prefer.

## 4. Start Claude Code in `ghost-bus-la` and paste this

```bash
cd ~/Documents/Projects/ghost-bus-la
claude
```

```text
Read CLAUDE.md, docs/SPEC.md, docs/research/day1-probe.md, docs/spec/06-learning.md, and both files in docs/decisions/. Then read docs/spec/01-data-pipeline.md sections 1 to 5.

This is a new repo. We are starting milestone M0 ("The archive is alive"). Before writing anything:

1. Tell me in ten lines what this project is, what M0 must deliver, and its acceptance test, so I can check that you understood.
2. The data-source probe is already done (docs/research/day1-probe.md). Tell me the three findings that most shape the ingest design, and draft ADR-021 from it for my review. Don't re-run the probe.
3. A scrapped repo at ../la-ghost-bus created a data bucket and a budget in AWS with Terraform (state in ../la-ghost-bus/infra/terraform.tfstate). Read its Terraform files only to learn what exists. Tell me whether you recommend importing those resources or destroying them, and why. Don't copy code or decision records from that repo.
4. Propose the M0 work as a list of small PRs in order. For each: what it contains, how it will be tested, and which parts are boilerplate versus parts I should predict first.

Then wait for my go-ahead. Follow the learning loop for every PR: ask for my prediction, build with tests first, walk me through the diff, and quiz me before we merge.
```

## 5. For every later milestone

```text
Read CLAUDE.md and its "Current state" section, then docs/SPEC.md section 6 for milestone M<N>, and the component spec(s) it touches.

1. Summarize the milestone's deliverables and acceptance test.
2. List any VERIFY items and open questions that must be settled first.
3. Propose the PRs in order, marking the owner-written piece(s) for this milestone.

Wait for my go-ahead.
```

## 6. Three habits that matter more than any tool

1. **Get the archive running first.** Metro's realtime stream shows only the present. Each day without the archive is history that can't be recovered.
2. **Never screenshot or paste secrets.** Clear the terminal before sharing a screen.
3. **Don't merge what you can't explain.** The quiz gate is the point of the project, not an obstacle to it.
