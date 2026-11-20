# Quiz 051 · Deploying the API stack

**How to take it (optional, ADR-022):** write your answer under each question, then open the model answer to compare. If you want a grade, tell Claude, who logs it in `docs/learning/quiz-log.md`.

---

## 1. What does this do?

`ALTER DEFAULT PRIVILEGES FOR ROLE pipeline IN SCHEMA serving GRANT SELECT ON TABLES TO api`. Why not `GRANT SELECT ON ALL TABLES IN SCHEMA serving TO api` alone?

**Your answer:**

>

<details>
<summary>Model answer</summary>

`GRANT ... ON ALL TABLES` covers tables that exist now. Publish creates a brand-new table on every load and renames it into place, so the next publish would leave the API unable to read anything. Default privileges apply to every future table `pipeline` creates in `serving`. `test_publish_as_pipeline_and_read_as_api` publishes twice and reads after each.

</details>

## 2. What does this do?

Why does the remote script read the passwords from SSM on the VM instead of the laptop sending them in the command?

**Your answer:**

>

<details>
<summary>Model answer</summary>

SSM Run Command keeps each command's parameters in its history, visible in the console and the API. A password in the command would be stored there indefinitely. The VM's role can read `/ghost-bus-la/*`, so the script fetches them itself, writes a `umask 077` file, and never echoes them. A test checks no command line contains "PASSWORD".

</details>

## 3. What breaks if…

…the deploy waited for `/readyz` to return 200?

**Your answer:**

>

<details>
<summary>Model answer</summary>

On a fresh VM nothing is published yet, so `/readyz` is 503 "stale" forever and every deploy would roll back, including one fixing a bug the pipeline needs. The gate accepts "stale" (the database answered, as the `api` role) and fails only "Database unavailable" or no answer. Freshness is alerted separately.

</details>

## 4. What breaks if…

…ingest were one more service in `compose.app.yml`?

**Your answer:**

>

<details>
<summary>Model answer</summary>

`up --remove-orphans`, a changed shared setting, or a rollback would recreate the ingest container during an API deploy, costing archive snapshots for an unrelated change (hard rule 3). Separate Compose projects mean an app deploy never touches it.

</details>

## 5. How would you change it to…

…deploy on merge to main instead of from the laptop?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Add a GitHub OIDC identity provider and a deploy role in Terraform that only this repo's `main` branch can assume, allowed `ssm:SendCommand` on this instance with `AWS-RunShellScript` and `ssm:GetCommandInvocation`. A workflow after the image build assumes it and runs `scripts/deploy_app.py <sha>`. It's an IAM change, so the plan goes to the owner first.

</details>
