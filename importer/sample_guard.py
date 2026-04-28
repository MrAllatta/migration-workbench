"""Guardrails for applying sample import bundles into local SQLite."""

from __future__ import annotations

from pathlib import Path


def live12_block_message_for_sample_into_dev_sqlite(
    *,
    data_dir: str,
    validate_only: bool,
    dry_run: bool,
    farm_sqlite_env: str,
    db_engine: str,
    db_name,
    base_dir: Path,
    allow_escape: bool = False,
) -> str | None:
    """Return a blocking message when sample bundle apply targets default dev sqlite."""
    if allow_escape:
        return None
    if validate_only or dry_run:
        return None
    if farm_sqlite_env.strip():
        return None
    if (db_engine or "").lower() != "django.db.backends.sqlite3":
        return None

    sample_root = (base_dir / "data" / "sample_import").resolve()
    raw = Path(data_dir).expanduser()
    resolved = raw.resolve() if raw.is_absolute() else (Path.cwd() / raw).resolve()
    try:
        if resolved != sample_root:
            return None
    except OSError:
        return None

    try:
        default_db = (base_dir / "db.sqlite3").resolve()
        active = Path(db_name).expanduser().resolve()
    except (OSError, TypeError):
        return None
    if active != default_db:
        return None

    return (
        "Refusing to load committed data/sample_import into default db.sqlite3 while "
        "FARM_SQLITE_PATH is unset (LIVE-12). Use validate-only, set FARM_SQLITE_PATH "
        "to a throwaway sqlite path, or opt in with an explicit escape flag."
    )
