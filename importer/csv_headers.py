"""CSV header detection utilities for Google Sheets exports.

Provides a centralized, testable approach to discovering real header rows in
CSV files exported from Google Sheets. These files often contain metadata
preamble rows, embedded newlines in quoted cells, and empty trailing columns
that break naive ``csv.DictReader`` usage.

Typical usage::

    from importer.csv_headers import build_reader

    reader = build_reader(
        csv_file,
        markers=["Harvest Year", "Crop"],
        aliases={"total supply": ["Total Supply", "Total\\nSupply"]},
    )
    for row in reader:
        process(row["crop"], row["total supply"])
"""

from __future__ import annotations

import csv
import fnmatch
import re
from pathlib import Path
from typing import Iterable


class HeaderNotFoundError(Exception):
    """Raised when a matching header row cannot be found within max_scan rows."""


# Instruction prefixes that identify rows as spreadsheet metadata rather than
# actual column headers. Matched case-insensitively against the first non-empty
# cell. This is a mutable list; product repos can extend it via
# ``register_preamble_prefix("my pattern")``.
_INSTRUCTIVE_PREFIXES = [
    "choose ",
    "step ",
    "green rows",
    "year,",
    "overide date",
    "field year,",
    "copy paste",
    "video -",
    "products to add",
    "fill col",
]


def register_preamble_prefix(prefix: str) -> None:
    """Register an additional preamble instruction prefix.

    Product repos can call this during app startup to extend the set of
    known instruction prefixes without patching upstream. The prefix is
    matched case-insensitively against the start of the first non-empty
    cell in each row.

    Args:
        prefix: The prefix string to add (e.g. ``"welcome to"``).
    """
    normalized = prefix.strip().lower()
    if not normalized:
        return
    existing_normalized = {p.strip().lower() for p in _INSTRUCTIVE_PREFIXES}
    if normalized not in existing_normalized:
        _INSTRUCTIVE_PREFIXES.append(normalized)

# Keywords that suggest a row is a header rather than data or metadata.
# At least one must appear (normalized) in a candidate header row.
HEADER_KEYWORDS = (
    "crop",
    "name",
    "date",
    "week",
    "block",
    "notes",
    "qty",
    "unit",
    "channel",
    "product",
    "location",
    "year",
    "variety",
    "amount",
    "harvest",
    "sales",
    "customer",
)


def normalize_field_name(name: str | None) -> str:
    """Normalize a CSV header cell into a case-insensitive lookup key.

    Collapses internal ``\\r`` and ``\\n`` into spaces, strips leading and
    trailing whitespace, lowercases, and collapses repeated whitespace into a
    single space.

    Args:
        name: Raw header cell value, possibly None.

    Returns:
        Normalized field name. Returns ``""`` when ``name`` is ``None`` or
        empty.
    """
    if not name:
        return ""
    cleaned = str(name).replace("\r", " ").replace("\n", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip().lower()


def _is_preamble_row(row: list[str]) -> bool:
    """Return True if the row looks like a title, instruction, or config row.

    Heuristics:
    - Fewer than 3 non-empty cells after stripping.
    - First non-empty cell starts with a known instruction prefix.
    - Every non-empty cell is numeric or date-like and contains no header
      keywords.

    Args:
        row: A list of cell strings from the CSV.

    Returns:
        True if the row should be skipped during header search.
    """
    non_empty = [cell.strip() for cell in row if cell.strip()]
    if len(non_empty) < 3:
        return True

    first = non_empty[0].lower()
    if any(first.startswith(prefix) for prefix in _INSTRUCTIVE_PREFIXES):
        return True

    keyword_present = any(
        keyword in normalize_field_name(cell)
        for cell in non_empty
        for keyword in HEADER_KEYWORDS
    )

    numeric_or_date_cells = 0
    for cell in non_empty:
        normalized = normalize_field_name(cell)
        if re.match(r"^\d+(\.\d+)?$", normalized):
            numeric_or_date_cells += 1
        elif re.match(r"^\d{4}-\d{2}-\d{2}$", normalized):
            numeric_or_date_cells += 1
        elif re.match(r"^\d{4},\d{1,2}$", normalized):
            numeric_or_date_cells += 1

    if keyword_present:
        return False

    return numeric_or_date_cells == len(non_empty)


def find_header_row(
    file_path: str | Path,
    markers: Iterable[str],
    *,
    max_scan: int = 20,
    min_nonempty: int = 3,
) -> int:
    """Return the 0-based index of the row containing all header markers.

    Parses the CSV with ``csv.reader`` so quoted cells with embedded newlines
    are handled correctly. Scans up to ``max_scan`` rows, skipping preamble
    rows, and returns the first row whose normalized cells contain every
    marker string.

    Args:
        file_path: Path to the CSV file.
        markers: Strings that must all appear in the real header row.
        max_scan: Maximum rows to scan before giving up.
        min_nonempty: Minimum non-empty cells a candidate row must have.

    Returns:
        Index of the discovered header row.

    Raises:
        HeaderNotFoundError: If no row matches within ``max_scan`` rows.
        ValueError: If ``markers`` is empty.
    """
    normalized_markers = [normalize_field_name(marker) for marker in markers if marker]
    if not normalized_markers:
        raise ValueError("At least one marker is required")

    with open(file_path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for row_index, row in enumerate(reader):
            if row_index >= max_scan:
                break

            non_empty = [cell.strip() for cell in row if cell.strip()]
            if len(non_empty) < min_nonempty:
                continue

            if _is_preamble_row(row):
                continue

            normalized_cells = {normalize_field_name(cell) for cell in row}
            if all(marker in normalized_cells for marker in normalized_markers):
                return row_index

    raise HeaderNotFoundError(
        f"Header row with markers {markers!r} not found in {file_path}"
        f" within {max_scan} rows"
    )


def build_reader(
    file_path: str | Path,
    markers: Iterable[str],
    *,
    aliases: dict[str, list[str]] | None = None,
    max_scan: int = 20,
    min_nonempty: int = 3,
) -> csv.DictReader:
    """Open a CSV and return a DictReader positioned at the real header row.

    Field names are normalized (lowercased, whitespace-collapsed). If
    ``aliases`` is provided, alternative header labels are rewritten to the
    canonical key so consumers can use a single field name regardless of which
    label appears in the file.

    Args:
        file_path: Path to the CSV file.
        markers: Strings that must all appear in the real header row.
        aliases: Mapping from canonical normalized name to alternative labels.
        max_scan: Maximum rows to scan before giving up.
        min_nonempty: Minimum non-empty cells a candidate row must have.

    Returns:
        A ``csv.DictReader`` whose fieldnames are normalized header cells.
        The reader is positioned so the first iteration yields the first data
        row after the real header.

    Raises:
        HeaderNotFoundError: If no matching header row is found.
    """
    header_index = find_header_row(
        file_path, markers, max_scan=max_scan, min_nonempty=min_nonempty
    )

    aliases = aliases or {}
    reverse_aliases: dict[str, str] = {}
    for canonical, alternatives in aliases.items():
        canonical_normalized = normalize_field_name(canonical)
        for alternative in alternatives:
            reverse_aliases[normalize_field_name(alternative)] = canonical_normalized

    with open(file_path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header_row: list[str] = []
        for _ in range(header_index + 1):
            header_row = next(reader)

        # Strip trailing empty header columns while preserving the original
        # positions of populated columns.
        while header_row and not normalize_field_name(header_row[-1]):
            header_row.pop()

        fieldnames = [
            reverse_aliases.get(
                normalize_field_name(cell),
                normalize_field_name(cell),
            )
            for cell in header_row
        ]

        remaining_rows = list(reader)

    # DictReader needs an iterable of strings. Re-serialize the remaining rows
    # into an in-memory buffer so the file handle can be closed before we
    # return the reader.
    import io
    text_buffer = io.StringIO()
    csv_writer = csv.writer(text_buffer)
    csv_writer.writerows(remaining_rows)
    text_buffer.seek(0)
    return csv.DictReader(text_buffer, fieldnames=fieldnames)


def find_header_row_from_cells(
    rows: list[list[str]],
    markers: Iterable[str],
    *,
    max_scan: int = 20,
    min_nonempty: int = 3,
) -> int:
    """Return the 0-based row index containing all header markers in cell data.

    Operates on a list of rows, where each row is a list of cell strings.
    This variant is useful for Google Sheets API data, deep-profile
    snapshots, or any pre-parsed tabular data that is not a CSV file.

    Args:
        rows: List of rows, each row being a list of cell strings.
        markers: Strings that must all appear in the real header row.
        max_scan: Maximum rows to scan before giving up.
        min_nonempty: Minimum non-empty cells a candidate row must have.

    Returns:
        Index of the discovered header row.

    Raises:
        HeaderNotFoundError: If no row matches within ``max_scan`` rows.
    """
    normalized_markers = [normalize_field_name(marker) for marker in markers if marker]
    if not normalized_markers:
        raise ValueError("At least one marker is required")

    for row_index in range(min(max_scan, len(rows))):
        row = rows[row_index]
        non_empty = [cell.strip() for cell in row if cell.strip()]
        if len(non_empty) < min_nonempty:
            continue

        if _is_preamble_row(row):
            continue

        normalized_cells = {normalize_field_name(cell) for cell in row}
        if all(marker in normalized_cells for marker in normalized_markers):
            return row_index

    raise HeaderNotFoundError(
        f"Header row with markers {markers!r} not found within {max_scan} rows"
    )


_YEAR_SUFFIX_RE = re.compile(r"_(\d{4})\.csv$")


class HeaderRegistry:
    """Registry mapping CSV path patterns to header markers and aliases.

    Import methods register their per-tab configuration once, then call
    ``build_reader_for`` instead of repeating markers in every call::

        from importer.csv_headers import header_registry

        header_registry.register(
            "weekly_ops/available_*",
            markers=["Harvest Year", "Crop"],
            aliases={"total supply": ["Total Supply", "Total\\nSupply"]},
        )

        for csv_file in glob.glob(...):
            reader = header_registry.build_reader_for(csv_file)
            ...

    The registry matches the longest subpath suffix (e.g. a registration
    for ``harvest_pack/pack_list_*`` takes priority over ``pack_list_*``).
    """

    def __init__(self) -> None:
        self._entries: list[tuple[str, list[str], dict[str, list[str]]]] = []

    def register(
        self,
        path_pattern: str,
        markers: list[str],
        aliases: dict[str, list[str]] | None = None,
    ) -> None:
        """Register header configuration for a path pattern.

        Args:
            path_pattern: Glob-like path pattern (e.g. ``weekly_ops/available_*``).
                Matching is by longest suffix, so more specific patterns take
                priority over less specific ones.
            markers: Header markers passed to ``build_reader``.
            aliases: Optional header aliases passed to ``build_reader``.
        """
        self._entries.append((path_pattern, markers, aliases or {}))

    def build_reader_for(
        self,
        csv_path: str,
    ) -> 'csv.DictReader':
        """Build a reader for *csv_path* using the best-matching registered config.

        Args:
            csv_path: Full path to the CSV file.

        Returns:
            A ``csv.DictReader`` configured per the matching registration.

        Raises:
            KeyError: If no registration matches ``csv_path``.
        """
        best_match: tuple[str, list[str], dict[str, list[str]]] | None = None
        for path_pattern, markers, aliases in self._entries:
            csv_basename = csv_path.rsplit("/", 1)[-1]
            if (
                fnmatch.fnmatch(csv_path, path_pattern)
                or fnmatch.fnmatch(csv_basename, path_pattern)
                or path_pattern in csv_path
            ):
                if best_match is None or len(path_pattern) > len(best_match[0]):
                    best_match = (path_pattern, markers, aliases)

        if best_match is None:
            raise KeyError(f"No header registration found for {csv_path}")

        _pattern, markers, aliases = best_match
        return build_reader(csv_path, markers=markers, aliases=aliases)


# Default global registry that import methods can populate.
header_registry = HeaderRegistry()


def iter_year_suffixed_csvs(
    pattern: str,
    *,
    default_year: int | None = None,
) -> list[tuple[str, int]]:
    """Glob for year-suffixed CSVs and extract the year from each filename.

    Matches filenames like ``available_2025.csv``, ``pack_list_2024.csv``.
    The four-digit year is extracted from the ``_YYYY`` suffix just before
    ``.csv``. Files that do not match the pattern are excluded.

    Args:
        pattern: Glob pattern passed to ``glob.glob()``.
        default_year: Fallback year when the regex does not match.
            When ``None``, non-matching files are excluded.

    Returns:
        List of ``(csv_path, year)`` tuples, sorted by filename.

    Example::

        for csv_path, year in iter_year_suffixed_csvs(
            os.path.join(self.data_dir, "weekly_ops/available_*.csv"),
        ):
            reader = build_reader(csv_path, markers=["Harvest Year", "Crop"])
            for row in reader:
                process(row, year=year)
    """
    import glob

    results: list[tuple[str, int]] = []
    for csv_path in sorted(glob.glob(pattern)):
        match = _YEAR_SUFFIX_RE.search(csv_path)
        if match:
            results.append((csv_path, int(match.group(1))))
        elif default_year is not None:
            results.append((csv_path, default_year))
    return results
