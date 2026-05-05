"""Bundle-tab CSV reader utilities for importer commands.

This module provides the first runtime slice for interpreting bundle tab
configuration against CSV files. It supports header normalization, alias-aware
header detection, column mapping, default values, and row iteration with source
row numbers.
"""

from __future__ import annotations

import csv
import os
import re
from collections.abc import Iterator


def _normalize_header(value: str) -> str:
    """Return a normalized header token for matching."""
    collapsed = re.sub(r"\s+", " ", (value or "").strip())
    return collapsed.casefold()


def _build_alias_lookup(aliases: dict[str, list[str]] | None) -> dict[str, str]:
    """Return normalized alias token -> canonical header label mapping."""
    lookup: dict[str, str] = {}
    for canonical, raw_aliases in (aliases or {}).items():
        lookup[_normalize_header(canonical)] = canonical
        for alias in raw_aliases or []:
            lookup[_normalize_header(alias)] = canonical
    return lookup


def _canonicalize_header(label: str, alias_lookup: dict[str, str]) -> str:
    """Return canonical label for *label* using alias lookup."""
    normalized = _normalize_header(label)
    return alias_lookup.get(normalized, label.strip())


def _detect_header_row(
    rows: list[list[str]],
    required_headers: list[str],
    alias_lookup: dict[str, str],
    max_scan_rows: int,
) -> int:
    """Return the 0-based index of the detected header row.

    Args:
        rows: Raw CSV rows from the source file.
        required_headers: Canonical required headers for the tab config.
        alias_lookup: Normalized alias lookup generated from config aliases.
        max_scan_rows: Number of rows to scan before failing.

    Returns:
        int: Zero-based index of the first matching header row.

    Raises:
        ValueError: If no row contains all required headers.
    """
    required = {_normalize_header(item) for item in required_headers}
    scan_limit = min(len(rows), max(max_scan_rows, 1))
    for idx in range(scan_limit):
        candidate = rows[idx]
        normalized_candidate = {
            _normalize_header(_canonicalize_header(cell, alias_lookup)) for cell in candidate if cell
        }
        if required.issubset(normalized_candidate):
            return idx
    raise ValueError(f"Unable to detect header row containing required headers: {required_headers}")


def iter_bundle_tab_rows(csv_path: str, tab_config: dict) -> Iterator[tuple[int, dict[str, str]]]:
    """Yield normalized rows for a bundle tab configuration.

    Args:
        csv_path: Absolute or relative path to the source CSV file.
        tab_config: Bundle tab configuration containing at least
            ``required_headers`` and optionally ``aliases``, ``column_map``,
            ``default_values``, and ``max_scan_rows``.

    Yields:
        tuple[int, dict[str, str]]: Pairs of ``(row_number, normalized_row)``
        where ``row_number`` is 1-based source file row number.

    Raises:
        FileNotFoundError: If *csv_path* does not exist.
        ValueError: If required headers are missing from scanned rows.
    """
    if not os.path.exists(csv_path):
        raise FileNotFoundError(csv_path)

    required_headers = tab_config.get("required_headers") or []
    aliases = tab_config.get("aliases") or {}
    column_map = tab_config.get("column_map") or {}
    default_values = tab_config.get("default_values") or {}
    max_scan_rows = int(tab_config.get("max_scan_rows", 200))

    alias_lookup = _build_alias_lookup(aliases)

    with open(csv_path, "r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))

    header_row_idx = _detect_header_row(rows, required_headers, alias_lookup, max_scan_rows)
    header_cells = rows[header_row_idx]
    canonical_headers = [_canonicalize_header(cell, alias_lookup) for cell in header_cells]

    for row_idx, row in enumerate(rows[header_row_idx + 1 :], start=header_row_idx + 2):
        values_by_header: dict[str, str] = {}
        for col_idx, header in enumerate(canonical_headers):
            raw_value = row[col_idx] if col_idx < len(row) else ""
            values_by_header[header] = (raw_value or "").strip()

        normalized_row: dict[str, str] = {}
        for output_key, source_header in column_map.items():
            normalized_row[output_key] = values_by_header.get(source_header, "")

        for key, value in default_values.items():
            normalized_row.setdefault(key, value)

        yield row_idx, normalized_row
