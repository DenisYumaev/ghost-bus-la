"""The committed OpenAPI document (API spec section 9).

`python -m ghostbus_api.openapi --write services/api/openapi.json` regenerates it (`make openapi`);
`--check` exits 1 if it is out of date. The document is built without touching a database: the
engine is lazy, so a placeholder URL is never connected to.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ghostbus_api.main import create_app

PLACEHOLDER_URL = "postgresql+psycopg://openapi@localhost/never-connected"


def document() -> dict[str, Any]:
    return create_app(PLACEHOLDER_URL).openapi()


def render() -> str:
    # Sorted keys and a trailing newline: a stable, reviewable diff.
    return json.dumps(document(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", type=Path, metavar="PATH")
    mode.add_argument("--check", type=Path, metavar="PATH")
    args = parser.parse_args(argv)
    text = render()
    if args.write:
        args.write.write_text(text)
        return 0
    current = args.check.read_text() if args.check.exists() else ""
    if current != text:
        print(f"{args.check} is out of date: run `make openapi`", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
