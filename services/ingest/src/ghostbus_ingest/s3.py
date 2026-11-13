"""S3 writes for ingest: the conditional PutObject contract from ADR-004 decision 2.

    200 -> "written"
    412 -> "duplicate": something is already at this content-addressed key, so the bytes are safe
    409 -> a concurrent conditional write is in flight: retry
    anything else -> raised, so the caller keeps the spool file and retries later

Only 412 may count as success. Treating any other error as "already stored" would let the
janitor delete a spool file that never reached S3.
"""

import time
from typing import Any, Literal, Protocol

from botocore.exceptions import ClientError

ALLOWED_PREFIXES = ("bronze/", "selftest/")
MAX_CONFLICT_RETRIES = 3

PutOutcome = Literal["written", "duplicate"]


class S3Client(Protocol):
    """The boto3 S3 calls ingest makes. boto3 has no type hints, so we declare our side."""

    def put_object(self, **kwargs: Any) -> dict[str, Any]: ...
    def get_object(self, **kwargs: Any) -> dict[str, Any]: ...
    def list_object_versions(self, **kwargs: Any) -> dict[str, Any]: ...
    def delete_object(self, **kwargs: Any) -> dict[str, Any]: ...


def http_status(error: ClientError) -> int:
    return int(error.response["ResponseMetadata"]["HTTPStatusCode"])


def conditional_put(
    s3: S3Client,
    bucket: str,
    key: str,
    body: bytes,
    content_type: str | None = None,
    retry_delay_s: float = 0.5,
) -> PutOutcome:
    """PutObject with If-None-Match: *. Ingest writes only under bronze/ (and selftest/)."""
    if not key.startswith(ALLOWED_PREFIXES) or ".." in key.split("/"):
        raise ValueError(f"refusing to write {key!r}: only keys under {ALLOWED_PREFIXES}")
    extra = {"ContentType": content_type} if content_type else {}
    for _attempt in range(MAX_CONFLICT_RETRIES):
        try:
            s3.put_object(Bucket=bucket, Key=key, Body=body, IfNoneMatch="*", **extra)
            return "written"
        except ClientError as error:
            status = http_status(error)
            if status == 412:
                return "duplicate"
            if status != 409:
                raise
        time.sleep(retry_delay_s)
    raise RuntimeError(f"still 409 Conflict after {MAX_CONFLICT_RETRIES} attempts for {key}")
