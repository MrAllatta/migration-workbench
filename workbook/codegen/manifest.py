"""Load and query a view-manifest YAML for admin code generation.

A view manifest (version ``"view-manifest-draft-1"``) is a sibling artifact
to the schema contract: it captures UI and workflow concerns (editable vs
computed fields, filter columns, status fields, tab sequence) that the
contract does not own.  The manifest may be hand-annotated after the
:doc:`discovery interview </workbook/discovery>`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def load_manifest(path: str | Path) -> dict[str, Any]:
    """Load a view-manifest YAML, validate, and return a normalised dict.

    Args:
        path: Filesystem path to a ``.yaml`` / ``.yml`` file.

    Returns:
        Normalised manifest dict with ``"version"``, ``"views"``, and
        ``"workflow_hints"`` keys guaranteed present.

    Raises:
        UserFacingError: if the file is unparseable, missing, or has an
            unsupported version.
    """
    import yaml

    src = Path(path).read_text(encoding="utf-8")
    raw: dict[str, Any] = yaml.safe_load(src)
    if not isinstance(raw, dict):
        from workbench.exceptions import UserFacingError

        raise UserFacingError(
            "View manifest must be a YAML mapping",
            action="Check that the manifest file is valid YAML with a top-level mapping.",
            check_id="WORKBOOK-MANIFEST-001",
        )

    version = str(raw.get("version") or "")
    expected = "view-manifest-draft-1"
    if version != expected:
        from workbench.exceptions import UserFacingError

        raise UserFacingError(
            f"Unsupported view manifest version: {version!r}",
            action=f"Set 'version' to {expected!r} in the manifest file.",
            check_id="WORKBOOK-MANIFEST-002",
        )

    raw.setdefault("views", [])
    raw.setdefault("workflow_hints", {})
    return raw


def find_view_for_entity(
    manifest: dict[str, Any], entity_name: str
) -> dict[str, Any] | None:
    """Return the first view entry whose ``entity`` matches *entity_name*.

    Args:
        manifest: Normalised view-manifest dict.
        entity_name: ``suggested_model_name`` from the schema contract
            (e.g. ``"crop"``).

    Returns:
        The matching view dict, or ``None`` if no view is bound to that
        entity.
    """
    for view in manifest.get("views") or []:
        if str(view.get("entity") or "") == entity_name:
            return view
    return None
