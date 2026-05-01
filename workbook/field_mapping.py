"""Map profiler column metadata to suggested Django field constructors.

Used by the ``scaffold_workbook_schema`` management command and the
:mod:`workbook.schema_contract` builder to produce an initial Django model
skeleton from profiler JSON artifacts.  All suggestions are *hints* — they
must be reviewed and adjusted before use in production migrations.

**Mapping rules** (in priority order):

1. Relation columns (``is_relation_type`` truthy) → ``ForeignKey``.
2. Numeric formats (``number``, ``slider``, ``percent``) → ``DecimalField``
   with high precision defaults.
3. Currency format → ``DecimalField`` with monetary precision.
4. Date / datetime formats → ``DateField`` / ``DateTimeField``.
5. Boolean (``checkbox``) → ``BooleanField``.
6. Text, rich-text, canvas, image, or unknown → ``TextField`` (safe default).

Nullability is promoted to non-null when the column's ``null_rate`` is ``0``
*and* the sample has at least 100 rows — below that threshold a
``"nullability_not_hardened_low_sample"`` note is appended instead.
"""

from __future__ import annotations

from typing import Any


def _slugify_header(name: str) -> str:
    s = "".join(c if c.isalnum() else "_" for c in name.strip())
    s = "_".join(x for x in s.split("_") if x)
    return s.lower() or "field"


def suggested_field_name(source_column: str) -> str:
    """Convert a source column header to a valid Django field name.

    Replaces any non-alphanumeric character with ``_``, collapses consecutive
    underscores, and lowercases the result.

    Args:
        source_column: Raw column header from the profiler or bundle config.

    Returns:
        str: Snake_case Django field name candidate.

    Example::

        >>> suggested_field_name("Crop Variety (2024)")
        'crop_variety_2024'
    """
    return _slugify_header(source_column)


def map_profiler_column_to_django_field(col: dict[str, Any]) -> dict[str, Any]:
    """Suggest a Django field class and kwargs for a profiler column summary.

    Reads column metadata produced by ``profile_coda_table`` or
    ``profile_coda_doc`` and returns a field hint dict that the schema
    contract builder embeds into its output JSON.

    Args:
        col: Profiler column summary dict.  Recognised keys:

            - ``format_type`` (str | None) — Coda column format.
            - ``name`` (str) — Column name (used in relation notes).
            - ``null_rate`` (float | None) — Fraction of null rows in sample.
            - ``sample_size`` / ``row_count_sample`` (int | None) — Sample size
              used to harden nullability decisions.
            - ``is_relation_type`` (bool | None) — Indicates a linked-row
              column that should become a ``ForeignKey``.
            - ``unique_count_sample`` (int | None) — Distinct values in sample;
              very low values suggest an enum or constant column.

    Returns:
        dict: Field hint with keys:

            - ``django_field_class`` (str) — e.g. ``"models.TextField"``.
            - ``django_field_kwargs`` (dict) — Keyword arguments for the field
              constructor.
            - ``notes`` (list[str]) — Advisory strings to embed in the
              contract JSON (e.g. ``"low_cardinality_sample"``).
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

    # Only remove null=True (promote to NOT NULL) when the sample is large enough
    # to trust a zero null_rate.  Small samples could simply have missed nulls.
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
    """Merge bundle required headers with profiler column metadata, required-first.

    Columns listed in *required_headers* appear first (in declaration order),
    followed by any additional profiler columns not already covered.  This
    ensures the importer's required header contract is always visible at the
    top of the generated schema.

    Args:
        col_meta: ``{column_name: profiler_column_dict}`` mapping from the
            profiler artifact.
        required_headers: Ordered list of column names declared as required in
            the bundle config.

    Returns:
        list[dict]: Merged column list, each entry being the profiler dict
        augmented with ``"name"`` guaranteed present.
    """
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
