"""Tab name sanitization utility for the connector pipeline.

Replaces reserved characters that would cause issues in YAML bare strings,
Python identifiers, or filesystem paths.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_RESERVED_CHARS: re.Pattern[str] = re.compile(r'[|:\\/*?"<>%]')


def sanitize_tab_name(name: str) -> str:
    """Replace reserved characters in *name* with underscore.

    Logs a warning when replacement occurs so the operator is aware of any
    renamed tab.

    Args:
        name: Raw tab title from the provider API.

    Returns:
        str: Sanitized tab name safe for YAML keys, Python identifiers, and
            filesystem paths.
    """
    sanitized = _RESERVED_CHARS.sub("_", name)
    if sanitized != name:
        logger.warning("Tab name sanitized: %r -> %r", name, sanitized)
    return sanitized
