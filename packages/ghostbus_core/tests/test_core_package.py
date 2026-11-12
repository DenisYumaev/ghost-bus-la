from pathlib import Path

import ghostbus_core


def test_package_ships_type_hints() -> None:
    # py.typed tells mypy that this package's type hints are public (PEP 561).
    assert (Path(ghostbus_core.__file__).parent / "py.typed").is_file()
