# ADR-004: Bronze storage and guardrails: content-addressed keys, conditional writes, deny-delete, instance role, remote state

- **Status:** Proposed. Both `VERIFY` items were confirmed on 2026-11-12 (results below). Accepted once the owner's "Why" rewrite lands, because accepted ADRs can't be edited (CLAUDE.md hard rule 13)
- **Date:** 2026-11-12
- **Supersedes:** ADR-001 decision 6's key format and duplicate check. Its partitioning by UTC fetch date and its fetch log stand
- **Evidence:** `docs/spec/01-data-pipeline.md` sections 2.4, 2.5, and 3; `docs/spec/05-infra-ops.md` section 2; ADR-021

## Context

Bronze is the only data that can't be rebuilt. Everything downstream is recomputed from it, and a snapshot that isn't stored is gone for good. Two writers can touch the same data: the uploader retrying after a crash, and later a re-run or backfill. So the storage design must make a duplicate write harmless and a destructive one impossible, enforced by AWS rather than by a rule in a README.

ADR-001 decision 6 keyed objects as `<fetched_at>_<sha16>` and skipped a write "if a file with that hash already exists". Checking first and then writing is two steps, and two writers can both pass the check before either writes.

## Decision

1. **Content-addressed keys.** The object key is derived from the bytes:

   | What | Key |
   | --- | --- |
   | Realtime snapshot | `bronze/<feed>/dt=YYYY-MM-DD/<sha16>.ndjson.gz` |
   | GTFS schedule ZIP | `bronze/gtfs_static/dt=YYYY-MM-DD/<sha16>.zip` |
   | Fetch-log upload | `bronze/_fetch_log/dt=YYYY-MM-DD/hour=HH/<sha16>.jsonl` |

   `sha16` is the first 16 hex characters of the SHA-256 of the uncompressed bytes. `dt` is the UTC fetch date: a storage partition, not the service date. The fetch time is recorded in the fetch log, not in the key. The full hash is also recorded there.

2. **Conditional writes.** Every write to `bronze/` is a `PutObject` with `If-None-Match: *`, so S3 stores the object only if nothing exists at that key, in one atomic step on S3's side.
   - `200`: written.
   - `412 Precondition Failed`: those bytes are already stored. Logged as `duplicate`, which counts as success.
   - `409 Conflict`: a concurrent conditional write to the same key is in flight. Retry, and the retry returns `200` or `412`.

   Uploads use a single `PutObject`, never a multipart upload: the largest object, the 22 MB GTFS ZIP, is far below the 5 GB single-request limit.

3. **AWS enforces the rules on the data bucket.** Its bucket policy, for every principal including administrators:
   - denies `s3:DeleteObject` and `s3:DeleteObjectVersion` on `bronze/*`;
   - denies `s3:PutObject` on `bronze/*` and `selftest/*` when the request carries no `If-None-Match` header (condition key `s3:if-none-match` is null), so nothing can overwrite a bronze object, even by mistake (`VERIFY`, see below);
   - denies any request not made over TLS.

   The bucket also has versioning on, public access blocked, SSE-S3 encryption, and `prevent_destroy` in Terraform.

4. **Prefixes have different lifecycles.**

   | Prefix | Holds | Lifecycle |
   | --- | --- | --- |
   | `bronze/` | Raw bytes | Never expires, never moves to a colder storage class |
   | `derived/` | Compacted and decoded Parquet; rebuildable from bronze | Partitions are overwritten whole. Old versions expire after 7 days, so rewrites don't pile up versions forever |
   | `selftest/` | Scratch objects for testing write behavior | Expire after 1 day |
   | (all) | | Incomplete multipart uploads aborted after 7 days |

5. **The VM uses an instance role, never access keys.** The role may put and get objects under `bronze/*` and `derived/*`, put and delete under `selftest/*`, list the bucket, write to the backups bucket, read specific SSM parameters, and use SSM Session Manager. It has no delete on `bronze/`. The instance requires IMDSv2 (the metadata service, which hands out the role's temporary credentials).

6. **Terraform state lives in S3.** A small `infra/bootstrap` configuration creates a versioned, private, `prevent_destroy` state bucket, and keeps its own state locally, because a bucket can't hold the state that creates it. The main configuration uses the S3 backend with S3's native lock file (`use_lockfile = true`, Terraform 1.10 or later), so no DynamoDB table is needed. Backend settings come from a gitignored `infra/backend.hcl`, so the account ID isn't committed.

7. **boto3 is the S3 client** for ingest and the pipeline. It is the standard AWS SDK for Python and supports `IfNoneMatch` on `put_object` (ADR-003, decision 4).

### `VERIFY` before acceptance (M0 `selftest/` check)

- A second `PutObject` with `If-None-Match: *` to an existing key in this **versioned** bucket returns `412`, and the stored object is unchanged.
- An unconditional `PutObject` to `selftest/` is denied by the bucket policy, which proves the `s3:if-none-match` condition works as written.

**Results, 2026-11-12** (`scripts/selftest_conditional_writes.py`, run from the owner's laptop as the `denis-dev` user against the data bucket; rerun with `make selftest-s3`):

| Check | Result |
| --- | --- |
| First `PutObject` with `If-None-Match: *` to a new key | `200`, written |
| Second one to the same key, versioned bucket | **`412`**, rejected |
| Stored object afterwards | First body kept |
| `PutObject` without `If-None-Match` | **`403 AccessDenied`** from the bucket policy |
| Versions of the key | Exactly 1 |

Both `VERIFY` items hold. Cleanup deleted every version, and the bucket held 0 objects and 0 delete markers afterwards. The deny applied to an administrator, which confirms it covers every principal.

## Why

<!-- OWNER: rewrite this paragraph in your own words before this PR merges (SPEC.md section 5). -->

If the key is a hash of the content, the same snapshot always lands on the same key, so a retry, a restart, or a second uploader can't create a duplicate. With a conditional write, the "does it exist?" check and the write happen as one step inside S3, so there is no race to lose. Putting the deny rules in the bucket policy means "bronze is sacred" holds even when the code has a bug or a person makes a mistake at the terminal. An instance role means there is no long-lived key on the VM to leak, which matters after the November 10 incident.

## Alternatives considered

- **Fetch time in the key, with list-before-write deduplication** (ADR-001 decision 6). There is a race: two writers both list, both see nothing, and both write. Every write also pays for a list request. S3's strong read-after-write consistency doesn't help, because the check and the write are still two separate requests.
- **S3 Object Lock** instead of a deny policy. Stronger: even the root user can't delete locked objects. But once Object Lock is enabled on a bucket it can never be disabled, and it needs retention periods for every object. The deny policy can be removed only by a deliberate, reviewed policy change, which is enough to stop bugs and accidents, the realistic threats here.
- **Moving old bronze objects to a colder storage class.** Each transition is charged per object, and the infrequent-access classes bill a 128 KB minimum per object. With thousands of small snapshots a day, the fees can exceed the saving. Compaction into `derived/` already handles query performance. Revisit after the M0 size measurement.
- **Access keys on the VM, or in GitHub.** Long-lived keys leak (2026-11-10). Instance roles and OIDC issue short-lived credentials automatically.
- **A DynamoDB table for state locking.** The older pattern; native S3 lock files replace it with one less resource.

## Consequences

- **The fetch log can't be uploaded under one fixed name per hour.** The pipeline spec uploads `hour=HH.jsonl` "when the hour closes and on shutdown", so a mid-hour restart would upload the same name twice with different content. The conditional write would reject the second upload, and the rest of that hour's log would be lost. Each upload is therefore content-addressed under `hour=HH/`, and readers take the union of the files and drop duplicate lines. `docs/spec/01-data-pipeline.md` section 2.5 is updated to match.
- A 64-bit hash prefix means a different snapshot could, in theory, collide with an existing key and be treated as a duplicate. With about 2,880 snapshots per feed per day, the chance within one day's partition is about 2 in 10 trillion. The full hash in the fetch log would show it.
- The same bytes fetched on two different UTC days are stored twice, once per `dt` partition. That's harmless, and it keeps every day's partition self-contained.
- The data bucket is the one imported from the scrapped repo (owner's decision, 2026-11-11), so its name is `la-ghost-bus-bronze-<account>` even though it holds `derived/` and `selftest/` as well. Bucket names can't be changed.
- Removing the deny policy takes a Terraform change and an `apply` the owner approves (CLAUDE.md hard rule 8), which is the intended friction.

## Would change if

- The `VERIFY` checks fail: then conditional writes are enforced in code only, and this ADR records that gap.
- Measured storage makes colder classes clearly cheaper, which would be a new ADR with the numbers.
- The project moves to a second AWS account or region (the M7 rebuild drill), which needs nothing new: names are derived from the account ID.
