"""Create the database passwords in SSM Parameter Store, once (infra spec, section 4).

    uv run python scripts/init_secrets.py      (or: make init-secrets)

Each password is generated here and stored as a SecureString under /ghost-bus-la/db/, only if
that parameter doesn't exist yet: an existing password is never replaced (the database already
holds it). Nothing is printed but the parameter names. The VM's role may read /ghost-bus-la/*
(infra/iam.tf); the deploy reads them on the VM.
"""

import secrets
import sys
from typing import Any

import boto3

NAMES = ("owner-password", "api-password", "pipeline-password")
PREFIX = "/ghost-bus-la/db/"


def ensure(ssm: Any) -> list[str]:
    """Create each missing parameter; return the names created."""
    created = []
    for name in NAMES:
        try:
            ssm.put_parameter(
                Name=PREFIX + name,
                Value=secrets.token_urlsafe(32),  # URL-safe: goes into connection URLs as is
                Type="SecureString",
                Overwrite=False,
                Description="LA Bus Reliability database password (scripts/init_secrets.py)",
            )
        except ssm.exceptions.ParameterAlreadyExists:
            continue
        created.append(PREFIX + name)
    return created


def main() -> int:
    created = ensure(boto3.client("ssm", region_name="us-west-2"))
    print("created: " + (", ".join(created) if created else "nothing (all exist)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
