"""Tests for ghostbus_ingest.s3.conditional_put: ADR-004 decision 2's status-code contract.

200 written, 412 duplicate (success), 409 retried, anything else raised. botocore's Stubber
replays canned responses offline and checks the exact parameters sent.
"""

from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from botocore.stub import Stubber
from ghostbus_ingest.s3 import conditional_put

BUCKET = "test-bucket"
KEY = "bronze/vehicle_positions/dt=2026-11-13/0123456789abcdef.ndjson.gz"
BODY = b"\x1f\x8b gzip bytes"


@pytest.fixture
def s3() -> Any:
    return boto3.client(
        "s3",
        region_name="us-west-2",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",  # noqa: S106 - deliberately fake; Stubber blocks network
    )


@pytest.fixture
def stub(s3: Any) -> Iterator[Stubber]:
    with Stubber(s3) as stubber:
        yield stubber
        stubber.assert_no_pending_responses()


def params(**extra: Any) -> dict[str, Any]:
    return {"Bucket": BUCKET, "Key": KEY, "Body": BODY, "IfNoneMatch": "*", **extra}


def test_new_key_is_written(s3: Any, stub: Stubber) -> None:
    stub.add_response("put_object", {"ETag": '"e"'}, params())
    assert conditional_put(s3, BUCKET, KEY, BODY) == "written"


def test_existing_key_412_is_a_duplicate(s3: Any, stub: Stubber) -> None:
    stub.add_client_error(
        "put_object", "PreconditionFailed", http_status_code=412, expected_params=params()
    )
    assert conditional_put(s3, BUCKET, KEY, BODY) == "duplicate"


def test_409_conflict_is_retried(s3: Any, stub: Stubber) -> None:
    stub.add_client_error(
        "put_object", "ConditionalRequestConflict", http_status_code=409, expected_params=params()
    )
    stub.add_response("put_object", {"ETag": '"e"'}, params())
    assert conditional_put(s3, BUCKET, KEY, BODY, retry_delay_s=0) == "written"


def test_gives_up_after_repeated_409s(s3: Any, stub: Stubber) -> None:
    for _ in range(3):
        stub.add_client_error(
            "put_object",
            "ConditionalRequestConflict",
            http_status_code=409,
            expected_params=params(),
        )
    with pytest.raises(RuntimeError, match="409"):
        conditional_put(s3, BUCKET, KEY, BODY, retry_delay_s=0)


@pytest.mark.parametrize(
    ("code", "status"), [("AccessDenied", 403), ("InternalError", 500), ("SlowDown", 503)]
)
def test_any_other_error_is_raised_never_treated_as_success(
    s3: Any, stub: Stubber, code: str, status: int
) -> None:
    # Quiz 007, question 3: misreading these as "duplicate" would delete unstored spool files.
    stub.add_client_error("put_object", code, http_status_code=status, expected_params=params())
    with pytest.raises(Exception, match=code):
        conditional_put(s3, BUCKET, KEY, BODY)


def test_content_type_is_sent_when_given(s3: Any, stub: Stubber) -> None:
    stub.add_response("put_object", {"ETag": '"e"'}, params(ContentType="application/gzip"))
    assert conditional_put(s3, BUCKET, KEY, BODY, content_type="application/gzip") == "written"


@pytest.mark.parametrize("key", ["derived/x.parquet", "bronze", "../bronze/x", "/bronze/x", ""])
def test_refuses_keys_outside_bronze_and_selftest(s3: Any, key: str) -> None:
    with pytest.raises(ValueError, match="refusing"):
        conditional_put(s3, BUCKET, key, BODY)
