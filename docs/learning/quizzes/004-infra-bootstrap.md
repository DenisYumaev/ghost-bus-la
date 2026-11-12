# Quiz 004 · PR #4 · Terraform state bucket (`infra/bootstrap`)

**How to take it:** write your answer under each question first, then open the model answer to compare. When you've finished, tell Claude, who grades your written answers and logs the score in `docs/learning/quiz-log.md`. The merge needs 4 of 5. A vague answer scores zero.

To reveal an answer: click **Model answer** on GitHub, or open VS Code's preview (`Cmd+Shift+V`) and click it there.

---

## 1. What does this do?

What is Terraform state, and why does the bootstrap configuration keep *its* state on your laptop while every other configuration keeps state in the bucket it creates?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**State** is Terraform's record of which real resources it manages: the mapping from `aws_s3_bucket.tfstate` in the code to the actual bucket in AWS, with every attribute. On each `plan`, Terraform compares code, state, and reality to decide what to create, change, or destroy. Without state, Terraform doesn't know it already made something and would try to create it again.

**Why local:** it's a chicken-and-egg problem. The state bucket doesn't exist until this configuration is applied, so this configuration can't store its state there. It keeps a small local `terraform.tfstate` (gitignored). That's acceptable because the bootstrap is applied once and rarely changed. If the file is lost, the fix is `terraform import`, and `prevent_destroy` protects the bucket in the meantime. Everything else uses the S3 backend, with versioning and a lock file.

**Must mention for full credit:** state maps code to real resources and drives plans; the bucket can't hold the state of the code that creates it; why losing the local file is recoverable.

</details>

---

## 2. What does this do?

The tests in `infra/bootstrap/tests/state_bucket.tftest.hcl` run with `command = apply`, yet they create nothing in AWS and need no credentials. How? And name one thing they *can't* check.

**Your answer:**

>

<details>
<summary>Model answer</summary>

They use a **mock provider** (`mock_provider "aws"`). Terraform runs the whole plan-and-apply cycle, but every call that would go to AWS is answered by the mock. Computed values are filled with placeholders, and `aws_caller_identity` returns the fixed account ID `123456789012`. So the tests check the *configuration*: the bucket name formula, versioning `Enabled`, all four public-access blocks, SSE-S3, `BucketOwnerEnforced`, and the TLS-deny policy. They run offline in CI with no AWS access (hard rule 10).

**Can't check (any one):**

- `default_tags` merging into `tags_all`, because the mock doesn't run AWS-provider logic, which is why that test was removed.
- `prevent_destroy`, which is a lifecycle meta-argument, not a resource attribute.
- Real AWS behavior: whether the policy is accepted, or whether the bucket name is free.

Those are checked by reading the real `terraform plan`.

**Must mention for full credit:** a mock provider answers instead of AWS; tests verify configuration, not real behavior; one concrete limitation.

</details>

---

## 3. What breaks if…

Someone removes `prevent_destroy = true` from the state bucket and later runs `terraform destroy` in `infra/bootstrap` by mistake. What happens, step by step, and what still protects you?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Without `prevent_destroy`, the destroy plan lists the bucket, and if it's approved, Terraform tries to delete it. Then:

- **`force_destroy = false` still saves the data.** S3 refuses to delete a bucket that isn't empty, and once the main configuration is using it, the bucket holds the state file and its versions. The bucket delete fails with `BucketNotEmpty`.
- The *other* resources (versioning, public access block, encryption, policy, lifecycle) **are** removed first, so the bucket survives but unprotected: the TLS-deny policy and public access block are gone, versioning is suspended, and the lifecycle rule is removed.
- If the bucket *were* empty (before first use), it would be deleted, and someone else could even claim the name.

If the state were truly lost, the main configuration would lose track of the data bucket, the VM, and the roles. Recovery would mean re-importing every resource by hand. That's why there are two locks (`prevent_destroy` in Terraform, `force_destroy = false` in AWS) plus hard rule 8: show the plan and wait for approval before any destroy.

**Must mention for full credit:** `force_destroy = false` blocks deleting a non-empty bucket; the settings resources would still be destroyed; the cost of losing state; the human gate (plan review).

</details>

---

## 4. What breaks if…

CI runs `terraform init -backend=false` before validating and testing. What would happen if it ran plain `terraform init` on the *main* configuration, which will use the S3 backend, and why shouldn't CI simply be given AWS keys to make that work?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Plain `init` on a configuration with a `backend "s3"` block tries to connect to the state bucket. CI has no AWS credentials, and no `backend.hcl` because it's gitignored, so `init` fails and every later step is blocked. `-backend=false` installs the providers and modules without touching remote state, which is all `validate` and `test` need.

**Why not just add keys:** long-lived AWS keys in GitHub secrets are exactly the kind of credential that leaks (the 2026-11-10 incident), and they would grant state access, which reveals every resource, to every workflow run. When CI does need AWS (the deploy in M2, or posting a `plan`), it assumes a narrowly scoped IAM role through **OIDC**: short-lived credentials issued per run, with no stored secret.

**Must mention for full credit:** `init` without the flag tries to reach the S3 backend and fails without credentials or `backend.hcl`; validate and test don't need state; OIDC roles instead of stored keys.

</details>

---

## 5. How would you change it to…

Old state versions expire after 90 days. Suppose you discover a bad state change from four months ago that you need to inspect. How would you change the configuration so this can't happen again, and what does that cost?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**The change:** raise or remove `noncurrent_version_expiration` in `aws_s3_bucket_lifecycle_configuration.tfstate`, for example to 365 days, or delete the rule and keep every version forever. Alternatively keep a count instead of an age: `newer_noncurrent_versions = 50` keeps the last 50 versions regardless of age. Plan, review, apply. The bootstrap is a normal Terraform configuration, just with local state.

**Cost:** state files are small (kilobytes to low megabytes) and S3 Standard costs about $0.023 per GB-month, so even years of versions cost cents. The real costs are slight: old versions hold old resource details, so there's more sensitive history to protect. That's a good reason the bucket blocks public access and denies non-TLS requests.

A strong answer also notes that the version you need is a *noncurrent* version of the state object in the bucket, retrieved by version ID. Nothing can bring back a version that has already expired, so change the rule before you need it.

**Must mention for full credit:** the specific setting (`noncurrent_version_expiration`, or `newer_noncurrent_versions`); plan and apply; the cost is negligible storage plus more sensitive history kept.

</details>
