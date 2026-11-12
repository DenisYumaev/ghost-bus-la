# Runbook

One entry per alert (infra spec, section 9). Each says what the alert means, how to confirm it, how to fix it, and how to verify the fix. Every alert rule links to its entry here.

Shell access to the VM is through SSM only:

```bash
aws ssm start-session --target "$(terraform -chdir=infra output -raw instance_id)"
```

---

## vm-status-check

**Alerts:** `ghost-bus-la-system-status-check`, `ghost-bus-la-instance-status-check` (CloudWatch, emailed through the `ghost-bus-la-ops-alerts` SNS topic).

**What it means**

- *System check failed:* the AWS hardware or network under the VM has a problem. The alarm has already triggered **recover**, which moves the same instance (same ID, disk, and private IP) to healthy hardware. While it's down, nothing is archived.
- *Instance check failed:* the VM's own operating system isn't responding: out of memory, kernel panic, a full disk, or a broken network configuration. The alarm has already triggered a **reboot**.

**How to confirm**

```bash
aws ec2 describe-instance-status --instance-ids <instance_id> --include-all-instances \
  --query 'InstanceStatuses[0].{state:InstanceState.Name,system:SystemStatus.Status,instance:InstanceStatus.Status}'
```

Both `ok` means the automatic action worked. Check the ingest heartbeat too: the VM can be healthy while the container isn't.

**How to fix, if it doesn't recover on its own**

1. *Instance check still failing after the reboot:* read the console output for the cause:
   `aws ec2 get-console-output --instance-id <instance_id> --latest --output text | tail -50`.
   Out of memory or a full disk usually shows there. If SSM connects, check `df -h`, `free -m`, and `docker ps`.
2. *System check still failing:* stop and start the instance (not reboot). That always moves it to new hardware:
   `aws ec2 stop-instances --instance-ids <instance_id>`, wait for `stopped`, then `aws ec2 start-instances …`.
   The public IP changes on stop and start (no Elastic IP until M2), which doesn't matter while the VM only makes outbound connections.
3. If the VM is beyond repair, rebuild it from Terraform. Bronze is safe in S3; only unuploaded spool files are lost.

**How to verify the fix**

Both status checks are `ok`; both alarms return to `OK`, which sends an email; the ingest heartbeat resumes; and the fetch log shows the gap as `network_error` rows or missing attempts, which is correct and expected.

**Afterwards**

An outage longer than 5 minutes, or any lost data, gets an incident write-up in `docs/incidents/` (ADR-003).
