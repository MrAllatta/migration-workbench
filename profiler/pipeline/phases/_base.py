"""Shared utility functions for phase modules.

Module-level functions that were previously static methods on
PipelineState. Phase modules import these directly rather than
going through ``self.*``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _load_json_artifact(path: str | Path | None, default: Any = None) -> Any:
    """Load a JSON artifact file, returning *default* on failure.

    Args:
        path: Path to JSON file, or ``None``.
        default: Fallback value if file is missing or unreadable.

    Returns:
        Parsed JSON content or *default*.
    """
    if not path:
        return default
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("failed to load artifact %s", p)
        return default


def _build_google_services() -> tuple[Any, Any]:
    """Build Google Drive and Sheets API service objects.

    Returns:
        tuple: ``(drive_service, sheets_service)`` or ``(None, None)``
        if the required packages are not installed.
    """
    try:
        from connectors.google_sheets import (
            DRIVE_READONLY_SCOPE,
            SHEETS_READONLY_SCOPE,
            build_google_service,
        )
    except ImportError:
        logger.warning("connectors.google_sheets not available")
        return None, None

    scopes = [SHEETS_READONLY_SCOPE, DRIVE_READONLY_SCOPE]
    drive_service = build_google_service("drive", "v3", scopes)
    sheets_service = build_google_service("sheets", "v4", scopes)
    return drive_service, sheets_service
