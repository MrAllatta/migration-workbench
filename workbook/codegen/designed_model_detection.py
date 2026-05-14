"""Analyse profile column data to suggest designed/aggregate model structures."""

from __future__ import annotations

from typing import Any


def find_column_overlap_groups(
    tab_columns: dict[str, set[str]],
    *,
    min_overlap_ratio: float = 0.5,
) -> list[dict[str, Any]]:
    """Group tabs by overlapping column sets.

    For every pair of tabs, compute the Jaccard-like overlap ratio
    (intersection / min(len_a, len_b)). Pairs exceeding
    ``min_overlap_ratio`` are returned as cluster entries.

    Args:
        tab_columns: Mapping of ``worksheet_title -> set_of_column_names``.
        min_overlap_ratio: Minimum intersection/min(len) ratio to form
            a cluster.  Defaults to ``0.5``.

    Returns:
        List of cluster dicts with keys ``tab_names``, ``shared_columns``,
        and ``unique_columns``.
    """
    tab_names = list(tab_columns.keys())
    clusters: list[dict[str, Any]] = []

    for i in range(len(tab_names)):
        for j in range(i + 1, len(tab_names)):
            name_a = tab_names[i]
            name_b = tab_names[j]
            cols_a = tab_columns[name_a]
            cols_b = tab_columns[name_b]
            shared = cols_a & cols_b
            min_len = min(len(cols_a), len(cols_b))
            if min_len == 0:
                continue
            ratio = len(shared) / min_len
            if ratio >= min_overlap_ratio:
                clusters.append(
                    {
                        "tab_names": [name_a, name_b],
                        "shared_columns": sorted(shared),
                        "unique_columns": {
                            name_a: sorted(cols_a - cols_b),
                            name_b: sorted(cols_b - cols_a),
                        },
                    }
                )

    return clusters


def suggest_designed_model(
    cluster: dict[str, Any],
    *,
    suggested_name: str,
    source_provider: str = "google_sheets",
) -> dict[str, Any]:
    """Emit a contract table skeleton for a designed/aggregate model.

    Args:
        cluster: Cluster dict from ``find_column_overlap_groups()``.
        suggested_name: Snake_case model name to use.
        source_provider: Provider identifier for the source.

    Returns:
        dict: Schema-contract ``tables`` entry with ``source_tab: null``,
            columns populated from shared columns, and extra_fields for
            tab-unique columns.
    """
    columns = [
        {
            "source_column": col,
            "suggested_field_name": col,
            "django_field_class": "models.TextField",
            "django_field_kwargs": {"blank": True},
        }
        for col in cluster["shared_columns"]
    ]
    extra_fields: list[dict[str, Any]] = []
    seen_unique: set[str] = set()
    for tab_cols in cluster["unique_columns"].values():
        for col in tab_cols:
            if col not in seen_unique:
                seen_unique.add(col)
                extra_fields.append(
                    {
                        "source_column": col,
                        "suggested_field_name": col,
                        "class": "TextField",
                        "kwargs": {"blank": True},
                    }
                )

    return {
        "bundle_worksheet_title": None,
        "source_tab": None,
        "suggested_model_name": suggested_name,
        "columns": columns,
        "extra_fields": extra_fields,
    }
