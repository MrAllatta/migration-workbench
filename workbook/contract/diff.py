"""Contract diff: cross-version comparison and migration safety.

Extracted from ``workbook/codegen/contract.py`` as part of e04
(contract-layer-split).

Owns:
- ``diff_contracts`` — compare two contract dicts
- ``migration_safety_checks`` — flag dangerous/warning-level changes
- Various ``_diff_*`` helpers for table and field comparison
"""

from __future__ import annotations

from typing import Any

from workbook.contract.accessors import get_fields, get_model_name


def diff_contracts(
    old: dict[str, Any],
    new: dict[str, Any],
) -> dict[str, Any]:
    """Compare two normalised schema contracts and return a structured diff.

    Compares tables (matched by ``suggested_model_name``), resolved fields
    per table, and ``model_meta`` options.  No fuzzy rename detection —
    models present in only one contract are reported as added/removed.

    Args:
        old: First (older) normalised contract dict.
        new: Second (newer) normalised contract dict.

    Returns:
        Dict keyed by diff category, or ``{}`` when contracts are identical.
    """
    old_tables = {get_model_name(t): t for t in (old.get("tables") or [])}
    new_tables = {get_model_name(t): t for t in (new.get("tables") or [])}

    old_names = set(old_tables)
    new_names = set(new_tables)

    added_models = sorted(new_names - old_names)
    removed_models = sorted(old_names - new_names)
    common_models = sorted(old_names & new_names)

    if not added_models and not removed_models and not common_models:
        return {}

    result: dict[str, Any] = {}
    if added_models:
        result["models_added"] = added_models
    if removed_models:
        result["models_removed"] = removed_models

    model_diffs: dict[str, Any] = {}
    for name in common_models:
        diff = _diff_tables(old_tables[name], new_tables[name])
        if diff:
            model_diffs[name] = diff

    if model_diffs:
        result["model_diffs"] = model_diffs

    return result


def _diff_tables(
    old_table: dict[str, Any],
    new_table: dict[str, Any],
) -> dict[str, Any] | None:
    """Compare two tables with the same model name.

    Returns a diff dict or ``None`` when no differences are found.
    """
    old_fields = _field_map(get_fields(old_table))
    new_fields = _field_map(get_fields(new_table))

    old_names = set(old_fields)
    new_names = set(new_fields)

    result: dict[str, Any] = {}

    # Field additions / removals.
    added = sorted(new_names - old_names)
    if added:
        result["fields_added"] = [_field_summary(new_fields[f]) for f in added]

    removed = sorted(old_names - new_names)
    if removed:
        result["fields_removed"] = [_field_summary(old_fields[f]) for f in removed]

    # Field changes.
    changed: list[dict[str, Any]] = []
    for fname in sorted(old_names & new_names):
        of = old_fields[fname]
        nf = new_fields[fname]
        fc = _diff_fields(of, nf)
        if fc:
            changed.append(fc)
    if changed:
        result["fields_changed"] = changed

    # Meta changes.
    meta_diff = _diff_meta(
        old_table.get("model_meta") or {},
        new_table.get("model_meta") or {},
    )
    if meta_diff:
        result["meta_changed"] = meta_diff

    return result if result else None


def _field_map(fields: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index a field list by ``name``."""
    return {f["name"]: f for f in fields}


def _field_summary(field: dict[str, Any]) -> dict[str, Any]:
    """Return a clean, comparable field dict."""
    return {
        "name": field["name"],
        "class": field["class"],
        "kwargs": dict(field.get("kwargs") or {}),
    }


def _diff_fields(
    old: dict[str, Any],
    new: dict[str, Any],
) -> dict[str, Any] | None:
    """Compare two fields with the same name.

    Returns a change dict or ``None`` when fields are identical.
    """
    cls_old = old.get("class", "")
    cls_new = new.get("class", "")
    kwargs_old = dict(old.get("kwargs") or {})
    kwargs_new = dict(new.get("kwargs") or {})

    # YAML parses null: as a Python None key — normalise to "null".
    kwargs_old = {("null" if k is None else k): v for k, v in kwargs_old.items()}
    kwargs_new = {("null" if k is None else k): v for k, v in kwargs_new.items()}

    class_changed = cls_old != cls_new

    all_kwargs_keys = sorted(set(kwargs_old) | set(kwargs_new))
    kwarg_diffs: dict[str, dict[str, Any]] = {}
    for k in all_kwargs_keys:
        v_old = kwargs_old.get(k)
        v_new = kwargs_new.get(k)
        if v_old != v_new:
            kwarg_diffs[k] = {"old": v_old, "new": v_new}

    if not class_changed and not kwarg_diffs:
        return None

    entry: dict[str, Any] = {
        "name": old["name"],
        "class": {"old": cls_old, "new": cls_new},
    }

    if kwarg_diffs:
        entry["kwargs"] = kwarg_diffs

    return entry


MIGRATION_SEVERITY_DANGER = "DANGER"
MIGRATION_SEVERITY_WARNING = "WARNING"


def migration_safety_checks(diffs: dict[str, Any]) -> list[dict[str, Any]]:
    """Inspect ``diff_contracts()`` output for migration safety risks.

    Checks for field removals, nullable→non-nullable changes, field type
    changes, ``max_length`` reductions, ``unique=True`` additions, and
    non-nullable fields added without defaults.

    Args:
        diffs: Output from :func:`diff_contracts`.

    Returns:
        List of risk items, each with ``severity`` (DANGER or WARNING),
        ``model``, ``field``, ``message``, and optional ``detail``.
        Empty list when no risks are found.
    """
    results: list[dict[str, Any]] = []

    for model_name, model_diff in (diffs.get("model_diffs") or {}).items():
        # Field removals.
        for f in model_diff.get("fields_removed") or []:
            results.append(
                {
                    "severity": MIGRATION_SEVERITY_DANGER,
                    "model": model_name,
                    "field": f["name"],
                    "message": "Field removed — existing data in source will be lost",
                    "detail": {"old_class": f.get("class", "")},
                }
            )

        # Field changes.
        for fc in model_diff.get("fields_changed") or []:
            fname = fc["name"]
            kwargs_diff = fc.get("kwargs") or {}

            # nullable → non-nullable
            null_old = kwargs_diff.get("null", {}).get("old")
            null_new = kwargs_diff.get("null", {}).get("new")
            if null_old is True and null_new is not True:
                results.append(
                    {
                        "severity": MIGRATION_SEVERITY_DANGER,
                        "model": model_name,
                        "field": fname,
                        "message": "Field changed from nullable to non-nullable — "
                        "migration will fail if null rows exist",
                        "detail": {"null": {"old": True, "new": null_new}},
                    }
                )

            # Field class changed
            class_change = fc.get("class")
            if class_change and class_change["old"] != class_change["new"]:
                results.append(
                    {
                        "severity": MIGRATION_SEVERITY_WARNING,
                        "model": model_name,
                        "field": fname,
                        "message": (
                            f"Field class changed: "
                            f"{_field_class_short(class_change['old'])} -> "
                            f"{_field_class_short(class_change['new'])}"
                            " — existing data may not cast cleanly"
                        ),
                        "detail": {
                            "old_class": class_change["old"],
                            "new_class": class_change["new"],
                        },
                    }
                )

            # max_length decreased
            max_old = kwargs_diff.get("max_length", {}).get("old")
            max_new = kwargs_diff.get("max_length", {}).get("new")
            if max_old is not None and max_new is not None and max_old > max_new:
                results.append(
                    {
                        "severity": MIGRATION_SEVERITY_WARNING,
                        "model": model_name,
                        "field": fname,
                        "message": (
                            f"max_length decreased: {max_old} -> {max_new}"
                            " — existing data may be truncated"
                        ),
                        "detail": {
                            "old_max_length": max_old,
                            "new_max_length": max_new,
                        },
                    }
                )

            # unique=True added
            unique_old = kwargs_diff.get("unique", {}).get("old")
            unique_new = kwargs_diff.get("unique", {}).get("new")
            if unique_new is True and unique_old is not True:
                results.append(
                    {
                        "severity": MIGRATION_SEVERITY_WARNING,
                        "model": model_name,
                        "field": fname,
                        "message": (
                            "unique=True added — "
                            "migration will fail if duplicate values exist"
                        ),
                        "detail": {"unique": {"old": unique_old, "new": True}},
                    }
                )

        # Field additions — check non-nullable without default.
        for f in model_diff.get("fields_added") or []:
            kwargs = f.get("kwargs") or {}
            null = kwargs.get("null")
            has_default = "default" in kwargs or null is True
            if not has_default:
                results.append(
                    {
                        "severity": MIGRATION_SEVERITY_WARNING,
                        "model": model_name,
                        "field": f["name"],
                        "message": (
                            "Non-nullable field added without default — "
                            "existing rows will need a backfill value"
                        ),
                        "detail": {"class": f.get("class", "")},
                    }
                )

    return results


def _diff_meta(
    old_meta: dict[str, Any],
    new_meta: dict[str, Any],
) -> dict[str, Any] | None:
    """Compare two ``model_meta`` dicts.

    Only keys present in ``DIFF_META_KEYS`` are compared.
    """
    DIFF_META_KEYS = {
        "unique_together",
        "indexes",
        "constraints",
        "ordering",
        "verbose_name",
        "db_table",
        "app_label",
    }
    result: dict[str, Any] = {}
    for key in DIFF_META_KEYS:
        v_old = old_meta.get(key)
        v_new = new_meta.get(key)
        if v_old != v_new:
            result[key] = {"old": v_old, "new": v_new}
    return result if result else None


def _field_class_short(raw: str) -> str:
    """Strip the ``models.`` prefix from a field class string."""
    return raw.removeprefix("models.")
