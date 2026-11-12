# Quiz 002 · PR #2 · Repo scaffold

**How to take it:** write your answer under each question first, then open the model answer to compare. When you've finished, tell Claude, who grades your written answers and logs the score in `docs/learning/quiz-log.md`. The merge needs 4 of 5. A vague answer scores zero.

To reveal an answer: click **Model answer** on GitHub, or open VS Code's preview (`Cmd+Shift+V`) and click it there.

---

## 1. What does this do?

What does `uv sync --all-packages --locked` do in CI, and what specifically does `--locked` protect against?

**Your answer:**

>

<details>
<summary>Model answer</summary>

It creates one virtual environment and installs every workspace member (`ghostbus-core`, `ghostbus-ingest`) plus the dev tools, at exactly the versions recorded in `uv.lock`.

`--locked` makes the command **fail** if `uv.lock` doesn't match the `pyproject.toml` files, for example when someone added a dependency but never re-locked. Without it, uv would quietly re-resolve, and CI could test different versions from the ones on your laptop or in production. With it, CI tests exactly what was committed: a reproducible build.

**Must mention for full credit:** installs the exact locked versions for all members; `--locked` fails on a stale lockfile instead of silently resolving new versions.

</details>

---

## 2. What does this do?

What does `services/ingest/tests/test_isolation.py` check, and why does it parse the code with `ast` instead of searching the text for `"ghostbus_core"`?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**Checks (hard rule 3):**

- No file under `services/ingest/src/` imports a forbidden top-level module: shared app code (`ghostbus_core`), database drivers, FastAPI, or DuckDB.
- `services/ingest/pyproject.toml` declares none of them as a dependency.

The point is that a bug in shared code, or a Postgres outage, can never stop the archive.

**Why `ast`:** it sees only *real import statements*. A text search would fail on a comment or docstring that merely mentions `ghostbus_core`, which is a false alarm. It also handles every import form: `import a.b`, `from a.b import c`, and relative imports (`from . import x`, which stay inside ingest and are allowed). The helper has its own test, so the checker itself is checked.

**Must mention for full credit:** both checks (imports and declared dependencies); the reason for the rule; `ast` avoids false matches in comments or strings and understands import syntax.

</details>

---

## 3. What breaks if…

Someone deletes the `*.tfstate` line from `.gitignore`, runs `terraform apply` in `infra/bootstrap/`, then `git add -A` and pushes. What leaks, and which of our other protections would and wouldn't catch it?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**What leaks:** Terraform state holds every attribute of every managed resource in plain text: the account ID, ARNs, the budget alert email, and for some resources secrets such as generated passwords. Pushed to GitHub (which will become public), it is exposed, and git history keeps it **even after the file is deleted**. Removing it then means rewriting history and rotating anything sensitive.

This is realistic: the bootstrap config deliberately keeps a *local* state file, because the bucket it creates can't hold its own state.

**Other protections:**

- *gitleaks in pre-commit* catches credential-shaped strings (keys, tokens) but **not** emails, account IDs, or ARNs, which aren't secrets by pattern.
- *gitleaks in CI* runs after the push, so the data is already on GitHub.
- *Nothing else* would stop it. That's why the ignore rule is the first line of defense, and why state for the main config lives in S3, not on disk.

**Must mention for full credit:** state contains sensitive plain-text data; history keeps it; gitleaks catches only secret-shaped strings, and CI is too late.

</details>

---

## 4. What breaks if…

The workflow pins actions to commit SHAs (`actions/checkout@3d3c42e…`). What could happen if it used `actions/checkout@v7` and that tag were moved?

**Your answer:**

>

<details>
<summary>Model answer</summary>

A git tag is a movable pointer. If a maintainer's account is compromised, an attacker can point `v7` at malicious code, and every workflow using `@v7` runs it on its next build with that workflow's token and secrets. This really happened: in March 2025 the `tj-actions/changed-files` tags were repointed to code that dumped CI secrets into build logs across thousands of repos.

A commit SHA is a hash of the content, so it can't be moved to different code.

Today our token is read-only, so the damage would be limited. But the deploy workflow (M2) will assume an AWS role through OIDC, and then a hijacked action could reach the production AWS account.

**The cost of pinning:** updates are manual (or done by Dependabot), and the version is only visible in the comment.

**Must mention for full credit:** tags are mutable and SHAs aren't; a moved tag runs attacker code with your CI's permissions; the stakes rise when CI gets AWS access.

</details>

---

## 5. How would you change it to…

`check_fixture_size.py` caps each fixture file at 1 MiB. How would you change it to also cap the **total** size of all fixtures at 10 MiB, and what test would you write first?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**Change:** add `MAX_TOTAL_BYTES = 10 * 1024 * 1024`; in `main`, sum `st_size` over every file in every fixture directory. If the sum exceeds the cap, print the total and the largest contributors (so the fix is obvious) and return 1. Keep the per-file check too, since the two limits catch different problems.

**First test (it must fail before the change):** in a temporary directory, create 11 fixture files of exactly 1 MiB each. Each one passes the per-file limit, but the total is 11 MiB. Assert that `main` returns 1 and that the error message mentions the total. Then add the boundary test: exactly 10 MiB in total passes. That mirrors the existing at-limit and one-byte-over tests.

**Must mention for full credit:** sum across all fixture files with its own constant; keep the per-file check; a failing test where every file passes individually but the total fails, plus the boundary case.

</details>
