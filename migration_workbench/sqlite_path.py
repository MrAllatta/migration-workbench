"""Resolve SQLITE_PATH for Django sqlite DATABASES['NAME'] (absolute vs BASE_DIR-relative)."""

from __future__ import annotations

from pathlib import Path


def resolve_sqlite_database_path(base_dir: Path, sqlite_path: str | None) -> Path:
    """Return the filesystem path to the SQLite database file.

    If ``sqlite_path`` is unset, use ``db.sqlite3`` under ``base_dir``.
    If set and absolute, use it as-is; otherwise join with ``base_dir``.
    """
    if not sqlite_path:
        return base_dir / "db.sqlite3"
    p = Path(sqlite_path)
    if p.is_absolute():
        return p
    return base_dir / sqlite_path
