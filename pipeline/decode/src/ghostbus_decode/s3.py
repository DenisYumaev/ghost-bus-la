"""The S3 calls the pipeline makes, behind small protocols so tests use an in-memory fake.

Credentials: the configured AWS profile or the VM's role (hard rule 9).
"""

from typing import Any, Protocol

BRONZE_PREFIX = "bronze/"


class ReadBucket(Protocol):
    def list_keys(self, prefix: str) -> list[str]: ...
    def get(self, key: str) -> bytes: ...


class Bucket(ReadBucket, Protocol):
    def put(self, key: str, body: bytes) -> None: ...
    def delete(self, key: str) -> None: ...


class BronzeWriteRefused(Exception):
    """The pipeline tried to write under bronze/, which only ingest writes (hard rule 1)."""


class S3Bucket:
    """`Bucket` over a boto3 S3 client. Refuses any write or delete under `bronze/`."""

    def __init__(self, client: Any, bucket: str) -> None:
        self._s3 = client
        self._bucket = bucket

    def list_keys(self, prefix: str) -> list[str]:
        pages = self._s3.get_paginator("list_objects_v2").paginate(
            Bucket=self._bucket, Prefix=prefix
        )
        return [obj["Key"] for page in pages for obj in page.get("Contents", [])]

    def get(self, key: str) -> bytes:
        body: bytes = self._s3.get_object(Bucket=self._bucket, Key=key)["Body"].read()
        return body

    def put(self, key: str, body: bytes) -> None:
        """Overwrite `key`. Derived data is rebuildable, so a plain put is intended here,
        unlike bronze's conditional put (ADR-004)."""
        if key.startswith(BRONZE_PREFIX):
            raise BronzeWriteRefused(key)
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=body)

    def delete(self, key: str) -> None:
        """Delete a derived object (a stale part file). Never under `bronze/`."""
        if key.startswith(BRONZE_PREFIX):
            raise BronzeWriteRefused(key)
        self._s3.delete_object(Bucket=self._bucket, Key=key)
