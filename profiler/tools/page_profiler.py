"""Page-composition profiler for Coda (Superhuman Docs).

Translates page markdown exports into structured metadata showing which
tables and views are embedded on each page.  This bridges the gap between
the raw table list (available via the REST API) and the actual page-level
UI layout that a human sees in the browser.
"""

from __future__ import annotations

import re
from typing import Any

import requests

from connectors.coda_source import export_page_markdown, list_pages

# ---------------------------------------------------------------------------
# Markdown table parser (lightweight, no external dependency)
# ---------------------------------------------------------------------------

# Matches a standard GFM table:
#   | h1 | h2 |
#   | --- | --- |
#   | v1 | v2 |
_TABLE_BLOCK = re.compile(
    r"^(\|.+\|)\n^(\|[-:| ]+\|)\n((?:^\|.+\|\n?)*)",
    re.MULTILINE,
)

# Matches a markdown heading (## or ###)
_HEADING = re.compile(r"^#{2,3}\s+(.+)$", re.MULTILINE)


def _parse_table_block(header_line: str, body: str) -> dict[str, Any]:
    """Parse one GFM table block into a dict with *headers* and *sample_rows*."""
    headers = [c.strip() for c in header_line.strip().strip("|").split("|")]
    rows: list[list[str]] = []
    for line in body.strip().split("\n"):
        line = line.strip()
        if not line or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append(cells)
    return {
        "headers": headers,
        "sample_rows": rows[:5],
        "row_count_preview": len(rows),
    }


def parse_page_markdown_for_tables(markdown_text: str) -> list[dict[str, Any]]:
    """Parse page markdown (from ``export_page_markdown``) into embedded tables.

    Returns a list of dicts, one per embedded table:
      *section* — the ``##`` heading that precedes the table (or ``""``)
      *headers* — column names
      *sample_rows* — up to 5 sample data rows
      *row_count_preview* — how many rows appeared on the page
    """
    tables: list[dict[str, Any]] = []

    # Split the page into sections based on ## headings.
    # We store the most recent heading before each table.
    sections = []
    for match in _HEADING.finditer(markdown_text):
        sections.append((match.start(), match.group(1)))

    for tmatch in _TABLE_BLOCK.finditer(markdown_text):
        header_line = tmatch.group(1)
        body = tmatch.group(3)

        # Find the section this table belongs to
        table_start = tmatch.start()
        section_name = ""
        for pos, heading in reversed(sections):
            if pos < table_start:
                section_name = heading
                break

        block = _parse_table_block(header_line, body)
        tables.append(
            {
                "section": section_name,
                "headers": block["headers"],
                "sample_rows": block["sample_rows"],
                "row_count_preview": block["row_count_preview"],
                "char_offset": tmatch.start(),
            }
        )

    return tables


# ---------------------------------------------------------------------------
# Page composition profiling
# ---------------------------------------------------------------------------


def _match_table_to_known(
    headers: list[str],
    known_tables: dict[str, list[str]],
) -> str | None:
    """Try to match a table's headers against known tables by column name overlap.

    Returns the known table name if a match is found, or ``None``.
    """
    if not headers:
        return None
    header_set = set(h.lower() for h in headers if h)
    best_name: str | None = None
    best_score = 0
    for name, cols in known_tables.items():
        known_set = set(c.lower() for c in cols if c)
        if not known_set:
            continue
        overlap = len(header_set & known_set)
        if overlap > best_score:
            best_score = overlap
            best_name = name
    # Require at least a 2-column overlap to declare a match
    return best_name if best_score >= 2 else None


def profile_page_composition(
    session: requests.Session,
    doc_id: str,
    known_tables: dict[str, list[str]] | None = None,
    max_pages: int = 100,
    skip_export: bool = False,
) -> list[dict[str, Any]]:
    """Profile page composition in a Coda doc.

    For each page in the doc, exports to markdown and extracts which tables
    are embedded on that page.

    Args:
        session: Authenticated Coda requests session.
        doc_id: Coda document id.
        known_tables: Optional dict mapping table name → list of column names.
            When provided, embedded tables are matched against known table
            names for identification.
        max_pages: Maximum number of pages to profile.
        skip_export: If True, skip the actual API export (for smoke tests).

    Returns:
        List of page composition dicts:
          *id* — page id
          *name* — page name
          *tables* — list of embedded table profiles
    """
    all_pages = list_pages(session, doc_id)

    # Build a lookup of page_id → page_name for parent resolution
    page_names: dict[str, str] = {p["id"]: p.get("name", "") for p in all_pages}

    pages_out: list[dict[str, Any]] = []
    for p in all_pages[:max_pages]:
        pid = p.get("id")
        pname = p.get("name", "")
        parent_id = (p.get("parent") or {}).get("id")
        parent_name = page_names.get(parent_id) if parent_id else None

        if skip_export or not pid:
            pages_out.append(
                {
                    "id": pid,
                    "name": pname,
                    "parent_page": parent_name,
                    "page_type": p.get("type"),
                    "has_content": False,
                    "tables": [],
                }
            )
            continue

        try:
            markdown_text = export_page_markdown(session, doc_id, pid)
        except Exception as exc:  # noqa: BLE001
            pages_out.append(
                {
                    "id": pid,
                    "name": pname,
                    "parent_page": parent_name,
                    "page_type": p.get("type"),
                    "has_content": False,
                    "export_error": f"{type(exc).__name__}: {exc}",
                    "tables": [],
                }
            )
            continue

        embedded_tables = parse_page_markdown_for_tables(markdown_text)

        # Try to match each embedded table against known tables
        if known_tables:
            for et in embedded_tables:
                match = _match_table_to_known(et["headers"], known_tables)
                if match:
                    et["matched_table_name"] = match

        pages_out.append(
            {
                "id": pid,
                "name": pname,
                "parent_page": parent_name,
                "page_type": p.get("type"),
                "has_content": True,
                "exported_char_count": len(markdown_text),
                "embedded_table_count": len(embedded_tables),
                "tables": embedded_tables,
            }
        )

    return pages_out
