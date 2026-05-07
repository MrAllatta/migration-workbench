from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import CommandError


def load_folder_id_from_config(config_path_value: str | None) -> str | None:
    """Return ``folder_id`` from a corpus config path.

    Args:
        config_path_value: JSON config path passed via ``--config``.

    Returns:
        str | None: Folder id string when present, otherwise ``None``.

    Raises:
        CommandError: When the config path is invalid or JSON is malformed.
    """
    if not config_path_value:
        return None

    config_path = Path(config_path_value).expanduser().resolve()
    if not config_path.exists():
        raise CommandError(f"Config not found: {config_path}")

    try:
        config_payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CommandError(f"Invalid JSON config {config_path}: {exc}") from exc

    folder_id = config_payload.get("folder_id")
    if folder_id is None:
        raise CommandError(f"Config {config_path} is missing required key 'folder_id'")
    if not isinstance(folder_id, str) or not folder_id.strip():
        raise CommandError(f"Config {config_path} has invalid 'folder_id'; expected non-empty string")

    return folder_id
