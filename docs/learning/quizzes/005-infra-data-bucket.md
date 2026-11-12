# Quiz 005 · PR #5 · Main Terraform: imported data bucket, policy, budget

**How to take it:** write your answer under each question first, then open the model answer to compare. When you've finished, tell Claude, who grades your written answers and logs the score in `docs/learning/quiz-log.md`. The merge needs 4 of 5. A vague answer scores zero.

To reveal an answer: click **Model answer** on GitHub, or open VS Code's preview (`Cmd+Shift+V`) and click it there.

---

## 1. What does this do?

The plan said **"8 to import, 0 to add, 4 to change, 0 to destroy."** What does "import" mean here, and why did the four changed resources show as changes rather than as creates?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**Import** means Terraform adopts a resource that already exists in AWS: it reads the real object and records it in *this* configuration's state, without creating or touching it. The `import` blocks in `infra/imports.tf` name each resource address and its real ID (the bucket name, or `account:budget-name`).

After importing, Terraform compares the imported reality with the code. Where they differ, it plans an **in-place update**:

- the **budget** gets the 50% and 80% alerts and new tags;
- the **bucket** gets new tags;
- the **lifecycle** gets the `derived/` and `selftest/` rules;
- the **policy** gets the deny-delete and deny-unconditional-write statements.

The other four (versioning, public access block, ownership, encryption) already matched the code, so they're import-only.

Without the import blocks, Terraform would try to *create* a bucket whose name is taken, and fail, or create a second budget.

**Must mention for full credit:** import adopts an existing resource into state without changing it; differences between reality and code then show as in-place updates; why that beats creating.

</details>

---

## 2. What does this do?

Explain each of the three statements in the data bucket's policy in one sentence, and say which principals they apply to.

**Your answer:**

>

<details>
<summary>Model answer</summary>

All three apply to **every principal (`"*"`)**: the VM's role, your `denis-dev` user, and even administrators. That's what makes them guardrails rather than permissions.

1. **`DenyInsecureTransport`:** any request to the bucket or its objects not made over TLS (HTTPS) is refused, so data can't be read or written in plain text on the network.
2. **`DenyBronzeDeletes`:** `DeleteObject` and `DeleteObjectVersion` are refused on `bronze/*`. Raw data and its old versions can't be deleted. Even a plain delete, which in a versioned bucket only adds a "delete marker", is refused.
3. **`DenyUnconditionalWrites`:** `PutObject` to `bronze/*` or `selftest/*` is refused unless the request carries `If-None-Match`, so no write can overwrite an existing object. Every write must be "create only if new." `selftest/` is included so the self-test can prove the statement works.

**Must mention for full credit:** all apply to every principal; one correct sentence for each statement; the no-overwrite meaning of the third.

</details>

---

## 3. What breaks if…

A future PR adds this lifecycle rule "to save money": `filter { prefix = "bronze/" }` with a transition to Glacier after 90 days. What stops it, and if it were somehow applied, what would actually go wrong?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**What stops it:** the `no_lifecycle_rule_touches_bronze` test in `infra/tests/data_bucket.tftest.hcl` fails, because it forbids any transition and any rule scoped to `bronze/`. CI's `infra` job goes red, and the PR can't merge. Then hard rule 8: the plan would show the new rule to the owner before any apply. Changing an ADR-004 decision would also need a new ADR (hard rule 13).

**If applied anyway:**

- **Cost:** each transition is charged per object, and colder classes bill a minimum object size. With thousands of small snapshots a day, the fees could exceed the saving (ADR-004).
- **Access:** Glacier Flexible Retrieval and Deep Archive objects can't be read directly. They must be restored first, which takes minutes to hours and costs money. Compaction, backfills, and the "rebuild everything from bronze" promise would all break or slow down badly.
- Note that a lifecycle transition doesn't delete, so the deny-delete policy wouldn't catch it. That's exactly why the test exists.

**Must mention for full credit:** the test fails in CI and the plan is reviewed; per-object fees; restore delays breaking backfills; the deny policy doesn't cover transitions.

</details>

---

## 4. What breaks if…

After this PR is applied, both repos' state files claim the same bucket and budget, until the old state is retired. What could go wrong if you ran `terraform apply` in the old `la-ghost-bus/infra` folder, and why does retiring its state file fix that?

**Your answer:**

>

<details>
<summary>Model answer</summary>

Two Terraform configurations managing one resource fight each other. Each apply "corrects" the resource back to its own code:

- The old config would **replace the bucket policy** with its TLS-only version, silently **removing `DenyBronzeDeletes` and `DenyUnconditionalWrites`**, and nothing would flag it until the new config's next plan.
- It would remove the 50% and 80% budget alerts and restore the old tags.
- A `terraform destroy` there could delete the budget. (The bucket is saved by `prevent_destroy` in the old code, and by being non-empty once ingest runs.)

**Retiring the state** (renaming the old `terraform.tfstate`) means the old config no longer *knows* it manages anything. Its plan would try to *create* resources, which fails because the names are taken, and a destroy has nothing to destroy. Exactly one configuration owns each resource. Renaming, rather than deleting, keeps the file as a record and is reversible.

**Must mention for full credit:** two configurations overwrite each other's changes; the concrete danger (the policy guardrails silently removed); with no state, the old config manages nothing; one owner per resource.

</details>

---

## 5. How would you change it to…

The budget emails one address. How would you change it so alerts also reach the Discord channel the infra spec uses for other alerts, and what would you check before trusting it?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**The change:** AWS Budgets can't post to Discord directly. It can notify an **SNS topic** (`subscriber_sns_topic_arns` on each `notification`). So:

1. Create an `aws_sns_topic`, with a topic policy allowing `budgets.amazonaws.com` to publish.
2. Add the topic ARN to each notification block, next to the email.
3. Deliver from SNS to Discord. SNS can't call a Discord webhook natively (it can't shape the JSON body Discord expects), so you need a small adapter: either AWS Chatbot (which targets Slack and Chime, not Discord), or a tiny Lambda that reformats the message and posts to the webhook. The Lambda is new infrastructure, so it needs an ADR under ADR-003, decision 4.

**Check before trusting it:**

- Trigger a test: temporarily set a threshold that's already exceeded (for example 1%), apply, and confirm both the email and the Discord message arrive. Then revert.
- Confirm the webhook URL is stored in SSM Parameter Store, not in Terraform code or state (hard rule 9).
- Add a runbook entry for `budget_threshold`, since every alert rule links to one (infra spec, section 9).

**Must mention for full credit:** SNS as the bridge (`subscriber_sns_topic_arns`); an adapter for Discord, which SNS can't call directly; the webhook secret kept out of code; an end-to-end test before trusting it.

</details>
