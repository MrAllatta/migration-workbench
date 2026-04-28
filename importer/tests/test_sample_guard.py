from pathlib import Path

from importer.base import live12_block_message_for_sample_into_dev_sqlite


def test_sample_guard_blocks_default_sqlite_apply(tmp_path):
    base_dir = tmp_path
    (base_dir / "data" / "sample_import").mkdir(parents=True)
    message = live12_block_message_for_sample_into_dev_sqlite(
        data_dir=str(base_dir / "data" / "sample_import"),
        validate_only=False,
        dry_run=False,
        farm_sqlite_env="",
        db_engine="django.db.backends.sqlite3",
        db_name=str(base_dir / "db.sqlite3"),
        base_dir=Path(base_dir),
        allow_escape=False,
    )
    assert message is not None


def test_sample_guard_allows_validate_only(tmp_path):
    base_dir = tmp_path
    (base_dir / "data" / "sample_import").mkdir(parents=True)
    message = live12_block_message_for_sample_into_dev_sqlite(
        data_dir=str(base_dir / "data" / "sample_import"),
        validate_only=True,
        dry_run=False,
        farm_sqlite_env="",
        db_engine="django.db.backends.sqlite3",
        db_name=str(base_dir / "db.sqlite3"),
        base_dir=Path(base_dir),
        allow_escape=False,
    )
    assert message is None
