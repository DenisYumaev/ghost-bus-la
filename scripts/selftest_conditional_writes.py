"""Verify S3 conditional writes on the data bucket: the two VERIFY items in ADR-004.

Checks, against the real bucket, under the scratch prefix selftest/ only:

1. A PutObject with If-None-Match: * to a new key is written (200).
2. A second one to the same key is rejected with 412 Precondition Failed, on a VERSIONED bucket.
3. The stored object still holds the first bytes.
4. A PutObject WITHOUT If-None-Match is denied by the bucket policy (s3:if-none-match condition).
5. Exactly one version of the object exists: nothing was overwritten.

Then it deletes every version it created (selftest/ objects also expire after a day).
It never touches bronze/ (CLAUDE.md hard rule 1). Credentials come from the standard AWS chain.

Usage:
    uv run python scripts/selftest_conditional_writes.py --bucket <data bucket>
"""

import argparse
import sys
import uuid
from dataclasses import dataclass

import boto3
from botocore.exceptions import ClientError

# The production write path: the self-test proves the code ingest actually runs (quiz 007, Q5).
from ghostbus_ingest.s3 import S3Client, conditional_put, http_status

SELFTEST_PREFIX = "selftest/"
BODY_A = b"ghost-bus-la conditional write self-test: first body\n"
BODY_B = b"ghost-bus-la conditional write self-test: second body\n"


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


def _require_selftest_key(key: str) -> None:
    if not key.startswith(SELFTEST_PREFIX):
        raise ValueError(
            f"refusing to write {key!r}: this script only writes under {SELFTEST_PREFIX}"
        )


def new_selftest_key() -> str:
    return f"{SELFTEST_PREFIX}conditional-write/{uuid.uuid4().hex}.txt"


def _versions(s3: S3Client, bucket: str, key: str) -> tuple[list[str], list[str]]:
    """Version IDs and delete-marker IDs for exactly this key."""
    page = s3.list_object_versions(Bucket=bucket, Prefix=key)
    versions = [v["VersionId"] for v in page.get("Versions", []) if v["Key"] == key]
    markers = [m["VersionId"] for m in page.get("DeleteMarkers", []) if m["Key"] == key]
    return versions, markers


def _cleanup(s3: S3Client, bucket: str, key: str) -> None:
    _require_selftest_key(key)
    versions, markers = _versions(s3, bucket, key)
    for version_id in versions + markers:
        s3.delete_object(Bucket=bucket, Key=key, VersionId=version_id)


def run_selftest(s3: S3Client, bucket: str, key: str) -> list[CheckResult]:
    """Run the five checks in order, then always clean up the key."""
    _require_selftest_key(key)
    results: list[CheckResult] = []
    try:
        first = conditional_put(s3, bucket, key, BODY_A)
        results.append(
            CheckResult(
                "first_conditional_write_is_written", first == "written", f"outcome={first}"
            )
        )

        second = conditional_put(s3, bucket, key, BODY_B)
        results.append(
            CheckResult(
                "second_conditional_write_is_rejected_with_412",
                second == "duplicate",
                f"outcome={second}",
            )
        )

        stored = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        results.append(
            CheckResult(
                "stored_object_is_unchanged",
                stored == BODY_A,
                "first body kept" if stored == BODY_A else "object was overwritten",
            )
        )

        try:
            s3.put_object(Bucket=bucket, Key=key, Body=BODY_B)
            denied, detail = False, "unconditional write SUCCEEDED: the policy did not deny it"
        except ClientError as error:
            code = error.response["Error"]["Code"]
            denied, detail = code == "AccessDenied", f"error={code} status={http_status(error)}"
        results.append(CheckResult("unconditional_write_is_denied_by_policy", denied, detail))

        versions, _markers = _versions(s3, bucket, key)
        results.append(
            CheckResult(
                "exactly_one_version_exists", len(versions) == 1, f"versions={len(versions)}"
            )
        )
    finally:
        _cleanup(s3, bucket, key)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--bucket", required=True, help="the data bucket name")
    parser.add_argument("--region", default="us-west-2")
    args = parser.parse_args(argv)

    s3 = boto3.client("s3", region_name=args.region)
    key = new_selftest_key()
    print(f"bucket={args.bucket} key={key}")
    results = run_selftest(s3, args.bucket, key)
    for r in results:
        print(f"{'PASS' if r.passed else 'FAIL'}  {r.name}  ({r.detail})")
    print("cleanup: all versions of the test key deleted")
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
