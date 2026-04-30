from pathlib import Path

from migration_workbench.sqlite_path import resolve_sqlite_database_path


def test_resolve_sqlite_database_path_default(tmp_path):
    base = Path(tmp_path)
    assert resolve_sqlite_database_path(base, None) == base / "db.sqlite3"
    assert resolve_sqlite_database_path(base, "") == base / "db.sqlite3"


def test_resolve_sqlite_database_path_relative(tmp_path):
    base = Path(tmp_path)
    assert resolve_sqlite_database_path(base, "var/db.sqlite3") == base / "var" / "db.sqlite3"


def test_resolve_sqlite_database_path_absolute():
    assert resolve_sqlite_database_path(Path("/app"), "/data/db.sqlite3") == Path("/data/db.sqlite3")
