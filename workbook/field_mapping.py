"""Map profiler column hints to suggested Django field constructors (strings)."""

from __future__ import annotations

from typing import Any


def _slugify_header(name: str) -> str:
    s = "".join(c if c.isalnum() else "_" for c in name.strip())
    s = "_".join(x for x in s.split("_") if x)
    return s.lower() or "field"


def suggested_field_name(source_column: str) -> str:
    return _slugify_header(source_column)


def map_profiler_column_to_django_field(col: dict[str, Any]) -> dict[str, Any]:
    """
    col: profiler column summary (profile_coda_table) or doc column meta (profile_coda_doc).
    Returns suggested django field line metadata for schema contracts.
    """
    fmt = col.get("format_type")
    name = col.get("name") or ""
    null_rate = col.get("null_rate")
    sample_size = col.get("sample_size") or col.get("row_count_sample")
    is_relation = col.get("is_relation_type")
    unique_sample = col.get("unique_count_sample")

    field_class = "models.TextField"
    field_kwargs: dict[str, Any] = {"blank": True}

    if is_relation:
        field_class = "models.ForeignKey"
        field_kwargs = {
            "to": "TODO_TargetModel",
            "on_delete": "models.PROTECT",
            "null": True,
            "blank": True,
        }
    elif fmt in ("number", "slider", "percent"):
        field_class = "models.DecimalField"
        field_kwargs = {"max_digits": 18, "decimal_places": 4, "null": True, "blank": True}
    elif fmt in ("currency",):
        field_class = "models.DecimalField"
        field_kwargs = {"max_digits": 14, "decimal_places": 2, "null": True, "blank": True}
    elif fmt in ("date",):
        field_class = "models.DateField"
        field_kwargs = {"null": True, "blank": True}
    elif fmt in ("dateTime", "datetime"):
        field_class = "models.DateTimeField"
        field_kwargs = {"null": True, "blank": True}
    elif fmt in ("checkbox",):
        field_class = "models.BooleanField"
        field_kwargs = {"null": True, "blank": True}
    elif fmt in ("text", "richText", "canvas", "image") or fmt is None:
        field_class = "models.TextField"
        field_kwargs = {"blank": True}

    if (
        null_rate is not None
        and null_rate == 0
        and isinstance(sample_size, int)
        and sample_size >= 100
        and "null" in field_kwargs
    ):
        field_kwargs.pop("null", None)

    out = {
        "django_field_class": field_class,
        "django_field_kwargs": field_kwargs,
        "notes": [],
    }
    if null_rate == 0 and (not isinstance(sample_size, int) or sample_size < 100):
        out["notes"].append("nullability_not_hardened_low_sample")
    if unique_sample is not None and unique_sample <= 1:
        out["notes"].append("low_cardinality_sample")
    if is_relation:
        out["notes"].append(f"relation_target_todo:{name}")
    return out


def merge_bundle_headers(col_meta: dict[str, dict[str, Any]], required_headers: list[str]) -> list[dict[str, Any]]:
    """Order columns: required_headers first (with meta), then remaining profile columns."""
    seen: set[str] = set()
    ordered: list[dict[str, Any]] = []
    for h in required_headers:
        key = h.strip()
        meta = col_meta.get(key) or {}
        merged = {"name": key, **meta}
        ordered.append(merged)
        seen.add(key)
    for name, meta in sorted(col_meta.items()):
        if name in seen:
            continue
        ordered.append({"name": name, **meta})
    return ordered
