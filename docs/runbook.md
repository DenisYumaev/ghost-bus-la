# Runbook

One entry per alert (infra spec, section 9). Each says what the alert means, how to confirm it, how to fix it, and how to verify the fix. Every alert rule links to its entry here.

Shell access to the VM is through SSM only:

```bash
aws ssm start-session --target "$(terraform -chdir=infra output -raw instance_id)"
```

Useful commands on the VM (`sudo -i` first; ingest runs as the Compose project `ghost-bus-la`):

```bash
cd /opt/ghost-bus-la
docker compose --project-name ghost-bus-la -f compose.ingest.yml --env-file .env ps
docker compose --project-name ghost-bus-la -f compose.ingest.yml --env-file .env logs --tail 50 ingest
docker exec ghost-bus-la-ingest-1 python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8081/healthz').read().decode())"
cat ingest.tag   # the SHA currently deployed
```

---

## ingest-heartbeat-missed

**Alert:** `ingest_heartbeat_missed` (Healthchecks.io check `ghost-bus-la ingest`, by email). No ping for 3 minutes.

**What it means.** Ingest pings only while *every* feed is healthy (a `written` or `duplicate` snapshot within three of its intervals). So one of these happened: the VM is down; the container is crash-looping or stopped; a stream has stopped producing snapshots (Metro down, a server-side change, a stuck connection); or the heartbeat URL can't be read (`heartbeat_disabled` in the logs). **While it lasts, cancellation history may be missing from the archive.**

**How to confirm**

1. Is the VM up? `aws ec2 describe-instance-status --instance-ids <id> --include-all-instances` (see [vm-status-check](#vm-status-check)).
2. Is the container running and healthy? `ps` (above). `Restarting` means a crash loop; read the logs.
3. Which feed is failing? `/healthz` (above) lists each feed's `seconds_since_success`.
4. Is it Metro? The fetch log lines show `connect_failed` or `disconnect` with close codes; `network_error` cuts mean nothing arrived.

**How to fix**

- Crash loop from bad config: the logs show `config_error`; fix the `.env` or redeploy.
- Crash loop from a bug: roll back by deploying the previous SHA (`make deploy-ingest SHA=<previous>`), then fix forward.
- A stream stuck connected but silent: restart the container (`... restart ingest`). The spool keeps everything already captured.
- Metro is down: nothing to fix. Confirm backoff in the logs (`connect_failed` spaced out to 60 s) and note the outage; the fetch log records it, so those trips will be `unknown`, not `missed`.
- `heartbeat_disabled`: the SSM parameter `/ghost-bus-la/heartbeat-url` is missing or unreadable. Store it, then restart the container.

**How to verify the fix.** `/healthz` returns `ok`; Healthchecks shows the check up again; new snapshots appear in `bronze/<feed>/dt=<today>/`.

**Afterwards.** An outage over 5 minutes, or any lost data, gets an incident write-up in `docs/incidents/` (ADR-003).

---

## ingest-deploy-failed

**When.** `make deploy-ingest` prints `DEPLOY FAILED`.

**What it means.** The new image didn't become healthy within 3 minutes. The remote script already **rolled back** to the previous SHA if there was one; the output says `rolled back to <sha>` or `rollback ALSO unhealthy`.

**How to fix.** Read the 30 log lines printed with the failure. Fix the cause in a PR, merge, and deploy the new SHA. If the rollback also failed, treat it as [ingest-heartbeat-missed](#ingest-heartbeat-missed): the archive may be down.

**Note.** A deploy restarts ingest. The gap is the stop (final cuts and upload, up to 90 s) plus startup; the fetch log shows it. Deploy only when the image changed (infra spec, section 6).

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
