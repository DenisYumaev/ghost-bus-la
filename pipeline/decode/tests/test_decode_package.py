from pathlib import Path

import duckdb
import ghostbus_decode


def test_package_ships_type_hints() -> None:
    # py.typed tells mypy that this package's type hints are public (PEP 561).
    assert (Path(ghostbus_decode.__file__).parent / "py.typed").is_file()


def test_duckdb_runs_in_process() -> None:
    # DuckDB 2.0: relations keep no result, so query through a connection's execute().
    with duckdb.connect() as con:
        assert con.execute("SELECT 40 + 2").fetchall() == [(42,)]
