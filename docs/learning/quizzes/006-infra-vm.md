# Quiz 006 · PR #7 · The VM, its role, and recovery alarms

**How to take it:** write your answer under each question first, then open the model answer to compare. When you've finished, tell Claude, who grades your written answers and logs the score in `docs/learning/quiz-log.md`. You need 4 of 5 before M0 closes. A vague answer scores zero.

To reveal an answer: click **Model answer** on GitHub, or open VS Code's preview (`Cmd+Shift+V`) and click it there.

---

## 1. What does this do?

The VM has no SSH key and no inbound ports. How do you get a shell on it, and how does the connection actually reach the VM if nothing can connect *in*?

**Your answer:**

>

<details>
<summary>Model answer</summary>

With **SSM Session Manager**: `aws ssm start-session --target <instance_id>`.

The SSM agent on the VM opens an **outbound** HTTPS connection to the AWS Systems Manager service and keeps it open. When you start a session, AWS checks your IAM permissions, then relays your terminal over that existing outbound connection. Nothing ever connects *into* the VM, so the security group needs no inbound rules and there's no port 22 to scan or brute-force.

The VM can register with SSM because its role has `AmazonSSMManagedInstanceCore`. Every session is authenticated by IAM (your MFA-protected user) and can be logged, which SSH keys can't offer.

**Must mention for full credit:** SSM Session Manager; the agent's outbound connection that sessions ride on; IAM authorization (the role's SSM policy, your user); no inbound port needed.

</details>

---

## 2. What does this do?

`metadata_options` sets `http_tokens = "required"` and `http_put_response_hop_limit = 2`. What do these two settings do, and why is the hop limit 2 rather than the default 1?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The **instance metadata service** (IMDS, at `169.254.169.254`) is how code on the VM gets the instance role's temporary credentials.

- **`http_tokens = "required"`** enforces **IMDSv2**: a caller must first send a `PUT` to get a session token, then present it on every read. That blocks the classic attack where a bug in a web app (server-side request forgery) is tricked into fetching the credentials URL with a simple `GET`. That's how the 2019 Capital One breach worked.
- **`http_put_response_hop_limit`** caps how many network hops the token response may travel. Docker containers sit one hop further away than the host, behind the bridge network. With a limit of 1, ingest running in a container couldn't get a token, so it couldn't get credentials, so it couldn't write to S3. A limit of 2 reaches containers but not anything further out.

**Must mention for full credit:** IMDS serves the role credentials; IMDSv2 means token first (protecting against SSRF); a hop limit of 2 lets containers one hop away get credentials.

</details>

---

## 3. What breaks if…

Someone removes `ignore_changes = [ami, user_data]` from the instance. A month later Canonical publishes a new Ubuntu image, and you run `terraform plan` for an unrelated change. What happens?

**Your answer:**

>

<details>
<summary>Model answer</summary>

The `aws_ssm_parameter` data source now returns the **new** AMI ID. The AMI of a running instance can't be changed in place, so the plan shows `aws_instance.app` **must be replaced** (destroyed and recreated), mixed in with the unrelated change.

If that were applied:

- Termination protection makes the destroy fail. That's the safety net, but the apply breaks halfway.
- If protection had been switched off, the VM would be terminated: the **spool** (snapshots not yet uploaded) is lost, the archive stops for the minutes the new VM takes to boot, and a capture-SLO gap appears.

`user_data` is the same: editing `cloud-init.yaml` would force a replacement too, even though cloud-init only runs on first boot.

`ignore_changes` makes Terraform ignore drift in those two fields, so OS upgrades become a deliberate, planned rebuild rather than a side effect.

**Must mention for full credit:** the data source returns a new AMI; the plan forces a replacement; the consequence (termination protection blocks it, or the spool is lost and the archive gaps); `ignore_changes` makes upgrades deliberate.

</details>

---

## 4. What breaks if…

The VM's role policy grants `s3:PutObject` on `bronze/*` but not `s3:DeleteObject`. The bucket policy also denies deletes on `bronze/*`. If one of these were removed, would bronze still be protected? Explain how IAM evaluates the two together.

**Your answer:**

>

<details>
<summary>Model answer</summary>

AWS evaluates a request against **all** applicable policies:

1. An **explicit deny** anywhere wins, always.
2. Otherwise the request needs an **explicit allow**: for a principal in the same account, from either its identity policy (the role) or the resource policy (the bucket).
3. Otherwise it's an implicit deny.

So:

- **Remove only the bucket-policy deny:** the role still has no `DeleteObject` allow, so the VM's delete is implicitly denied. Bronze is safe *from the VM*. But your admin user (`AdministratorAccess`, which allows `s3:*`) could now delete bronze, by accident or with a buggy script.
- **Add `DeleteObject` to the role but keep the bucket deny:** the explicit deny wins, and the delete still fails.

That's defense in depth: the role is least privilege (it shouldn't even ask), and the bucket policy is the backstop for *every* principal, including administrators. Each layer covers the other's failure.

**Must mention for full credit:** explicit deny beats any allow; an allow is needed from the identity or resource policy; the outcome of removing each layer, including the admin user; defense in depth.

</details>

---

## 5. How would you change it to…

In M2 the VM resizes to `t4g.medium` and serves the API on ports 80 and 443. What changes in this Terraform, and what happens to the running VM during that apply?

**Your answer:**

>

<details>
<summary>Model answer</summary>

**Changes:**

- `instance_type = "t4g.medium"`. The validation allows it, and anything bigger is rejected.
- Two `ingress` blocks on `aws_security_group.app`: TCP 80 and 443 from `0.0.0.0/0` (Caddy redirects 80 to 443 and serves TLS). Still never 22. The `security_group_has_no_inbound_rules` test must change too, to allow exactly 80 and 443.
- An **Elastic IP** (`aws_eip`) attached to the instance, so the API's DNS record survives stop and start (infra spec, section 2).

**During apply:** a type change is **in place, but needs a stop and start**. Terraform stops the instance, changes the type, and starts it. Expect a few minutes of downtime: the archive gaps for that window, which the fetch log records. The spool on the EBS disk survives, so nothing already captured is lost. Without an Elastic IP, the public IP would also change on that stop. Security group changes apply instantly, with no restart.

Do it at a quiet hour, announce the gap, and note it against the capture SLO budget.

**Must mention for full credit:** the type change plus 80/443 ingress (and updating the test); an Elastic IP for stable DNS; a stop and start, so a short archive gap but the disk survives.

</details>
