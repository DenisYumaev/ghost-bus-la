"""Tests for scripts/selftest_conditional_writes.py (ADR-004 VERIFY items).

botocore's Stubber replays canned S3 responses in order, so these tests run offline and
also pin down exactly which requests the self-test makes.
"""

import io
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber
from selftest_conditional_writes import (
    BODY_A,
    BODY_B,
    conditional_put,
    new_selftest_key,
    run_selftest,
)

BUCKET = "test-bucket"
KEY = "selftest/conditional-write/abc.txt"


@pytest.fixture
def s3() -> Any:
    # Fake credentials: the client is never allowed to reach the network.
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


def _put_ok(stub: Stubber, body: bytes, conditional: bool = True) -> None:
    params: dict[str, Any] = {"Bucket": BUCKET, "Key": KEY, "Body": body}
    if conditional:
        params["IfNoneMatch"] = "*"
    stub.add_response("put_object", {"ETag": '"etag"'}, params)


def _put_error(
    stub: Stubber, code: str, status: int, body: bytes, conditional: bool = True
) -> None:
    params: dict[str, Any] = {"Bucket": BUCKET, "Key": KEY, "Body": body}
    if conditional:
        params["IfNoneMatch"] = "*"
    stub.add_client_error(
        "put_object", service_error_code=code, http_status_code=status, expected_params=params
    )


def _get(stub: Stubber, body: bytes) -> None:
    stub.add_response(
        "get_object",
        {"Body": StreamingBody(io.BytesIO(body), len(body))},
        {"Bucket": BUCKET, "Key": KEY},
    )


def _versions(stub: Stubber, version_ids: list[str], markers: list[str] | None = None) -> None:
    stub.add_response(
        "list_object_versions",
        {
            "Versions": [{"Key": KEY, "VersionId": v} for v in version_ids],
            "DeleteMarkers": [{"Key": KEY, "VersionId": m} for m in markers or []],
        },
        {"Bucket": BUCKET, "Prefix": KEY},
    )


def _cleanup(stub: Stubber, version_ids: list[str]) -> None:
    _versions(stub, version_ids)
    for v in version_ids:
        stub.add_response("delete_object", {}, {"Bucket": BUCKET, "Key": KEY, "VersionId": v})


# --- conditional_put -------------------------------------------------------------------------


def test_conditional_put_new_key_is_written(s3: Any, stub: Stubber) -> None:
    _put_ok(stub, BODY_A)
    assert conditional_put(s3, BUCKET, KEY, BODY_A) == "written"


def test_conditional_put_existing_key_is_duplicate(s3: Any, stub: Stubber) -> None:
    _put_error(stub, "PreconditionFailed", 412, BODY_A)
    assert conditional_put(s3, BUCKET, KEY, BODY_A) == "duplicate"


def test_conditional_put_retries_a_409_conflict(s3: Any, stub: Stubber) -> None:
    _put_error(stub, "ConditionalRequestConflict", 409, BODY_A)
    _put_error(stub, "PreconditionFailed", 412, BODY_A)
    assert conditional_put(s3, BUCKET, KEY, BODY_A, retry_delay_s=0) == "duplicate"


def test_conditional_put_gives_up_after_repeated_409s(s3: Any, stub: Stubber) -> None:
    for _ in range(3):
        _put_error(stub, "ConditionalRequestConflict", 409, BODY_A)
    with pytest.raises(RuntimeError, match="409"):
        conditional_put(s3, BUCKET, KEY, BODY_A, retry_delay_s=0)


def test_conditional_put_refuses_any_key_outside_selftest(s3: Any) -> None:
    # Bronze is sacred (hard rule 1): this script may never write there.
    with pytest.raises(ValueError, match="selftest/"):
        conditional_put(s3, BUCKET, "bronze/vehicle_positions/x.ndjson.gz", BODY_A)


# --- run_selftest ----------------------------------------------------------------------------


def test_all_checks_pass_when_s3_behaves_as_adr_004_expects(s3: Any, stub: Stubber) -> None:
    _put_ok(stub, BODY_A)  # 1. first conditional write: 200
    _put_error(stub, "PreconditionFailed", 412, BODY_B)  # 2. second conditional write: 412
    _get(stub, BODY_A)  # 3. object unchanged
    _put_error(stub, "AccessDenied", 403, BODY_B, conditional=False)  # 4. policy denies
    _versions(stub, ["v1"])  # 5. exactly one version
    _cleanup(stub, ["v1"])

    results = run_selftest(s3, BUCKET, KEY)

    assert [(r.name, r.passed) for r in results] == [
        ("first_conditional_write_is_written", True),
        ("second_conditional_write_is_rejected_with_412", True),
        ("stored_object_is_unchanged", True),
        ("unconditional_write_is_denied_by_policy", True),
        ("exactly_one_version_exists", True),
    ]


def test_fails_when_second_write_overwrites(s3: Any, stub: Stubber) -> None:
    _put_ok(stub, BODY_A)
    _put_ok(stub, BODY_B)  # S3 ignored If-None-Match
    _get(stub, BODY_B)
    _put_error(stub, "AccessDenied", 403, BODY_B, conditional=False)
    _versions(stub, ["v1", "v2"])
    _cleanup(stub, ["v1", "v2"])

    results = {r.name: r.passed for r in run_selftest(s3, BUCKET, KEY)}

    assert results["second_conditional_write_is_rejected_with_412"] is False
    assert results["stored_object_is_unchanged"] is False
    assert results["exactly_one_version_exists"] is False


def test_fails_when_policy_allows_unconditional_write(s3: Any, stub: Stubber) -> None:
    _put_ok(stub, BODY_A)
    _put_error(stub, "PreconditionFailed", 412, BODY_B)
    _get(stub, BODY_A)
    _put_ok(stub, BODY_B, conditional=False)  # the deny statement didn't fire
    _versions(stub, ["v1", "v2"])
    _cleanup(stub, ["v1", "v2"])

    results = {r.name: r.passed for r in run_selftest(s3, BUCKET, KEY)}

    assert results["unconditional_write_is_denied_by_policy"] is False
    assert results["exactly_one_version_exists"] is False


def test_cleanup_runs_even_when_a_check_raises(s3: Any, stub: Stubber) -> None:
    _put_ok(stub, BODY_A)
    _put_error(stub, "InternalError", 500, BODY_B)  # unexpected: not 200, 409, or 412
    _cleanup(stub, ["v1"])

    with pytest.raises(Exception, match="InternalError"):
        run_selftest(s3, BUCKET, KEY)


def test_cleanup_also_removes_delete_markers(s3: Any, stub: Stubber) -> None:
    _put_ok(stub, BODY_A)
    _put_error(stub, "PreconditionFailed", 412, BODY_B)
    _get(stub, BODY_A)
    _put_error(stub, "AccessDenied", 403, BODY_B, conditional=False)
    _versions(stub, ["v1"])
    _versions(stub, ["v1"], markers=["m1"])
    stub.add_response("delete_object", {}, {"Bucket": BUCKET, "Key": KEY, "VersionId": "v1"})
    stub.add_response("delete_object", {}, {"Bucket": BUCKET, "Key": KEY, "VersionId": "m1"})

    run_selftest(s3, BUCKET, KEY)


def test_default_key_is_unique_and_under_selftest() -> None:
    first, second = new_selftest_key(), new_selftest_key()
    assert first.startswith("selftest/conditional-write/")
    assert first != second
