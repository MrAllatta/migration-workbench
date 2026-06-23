"""Cell-level formula dependency analysis for profiler output.

Parses Google Sheets formulas into structured references and builds
a dependency graph to identify cross-sheet edges, high-value nodes,
formula pattern clusters, and FK candidates.

This is a port of selected components from gsheet-analyzer
(~/projects/gsheet-analyzer), adapted to migration-workbench's
profiler cell data format.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class Ref:
    """A single reference found inside a formula."""

    type: Literal["cell", "range", "named_range", "external_workbook", "importrange"]
    qualified_address: str
    sheet: str
    cell_start: str | None = None
    cell_end: str | None = None
    is_cross_sheet: bool = False
    is_named_range: bool = False
    is_external: bool = False
    external_spreadsheet_id: str | None = None


@dataclass
class ParsedFormula:
    """One formula cell after parsing."""

    source_sheet: str
    source_cell: str
    raw_formula: str
    references: list[Ref] = field(default_factory=list)
    functions_called: list[str] = field(default_factory=list)
    is_array_formula: bool = False
    pattern_id: str = ""
    pattern_hash: str = ""


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Sheet-qualified reference: 'Sheet Name'!A1:B10 or Sheet1!$A$1
_SHEET_REF_RE = re.compile(
    r"(?:"
    r"'([^']+)'"           # group 1 — quoted sheet name
    r"|"
    r"([A-Za-z0-9_.\-]+)"  # group 2 — unquoted sheet name
    r")"
    r"!"
    r"(\$?[A-Z]{1,3}(?:\$?\d+)?(?::\$?[A-Z]{1,3}(?:\$?\d+)?)?)",
    re.IGNORECASE,
)

# Bare local reference: A1  $B$2  C3:D10  $A$1:$Z$100
_LOCAL_REF_RE = re.compile(
    r"(?<![!A-Za-z\d$])"          # not preceded by !, letter, digit, $
    r"\$?([A-Z]{1,3})"            # group 1 — column letters
    r"\$?(\d+)"                   # group 2 — row number
    r"(?::\$?([A-Z]{1,3})\$?(\d+))?",  # groups 3-4 — optional range end
)

_CELL_RE = re.compile(r"([A-Z]{1,3})(\d+)", re.IGNORECASE)

# External references
_IMPORTRANGE_RE = re.compile(r'\bIMPORTRANGE\s*\(', re.IGNORECASE)
_EXTERNAL_REF_RE = re.compile(r'\[.+?\]')

# Function call extraction
_FUNCTION_RE = re.compile(r'\b([A-Z][A-Z0-9_]*)\s*\(', re.IGNORECASE)


# ---------------------------------------------------------------------------
# Reference parsing
# ---------------------------------------------------------------------------


def _parse_ref_from_match(m: re.Match, home_sheet: str) -> Ref | None:
    """Convert a sheet-qualified regex match to a Ref object."""
    sheet_name = m.group(1) or m.group(2)
    cell_part = m.group(3).upper().replace("$", "")

    if ":" in cell_part:
        left, right = cell_part.split(":", 1)
        lm = _CELL_RE.match(left)
        rm = _CELL_RE.match(right)
        if lm and rm:
            return Ref(
                type="range",
                qualified_address=f"{sheet_name}!{cell_part}",
                sheet=sheet_name,
                cell_start=lm.group(1) + lm.group(2),
                cell_end=rm.group(1) + rm.group(2),
                is_cross_sheet=sheet_name != home_sheet,
            )
        elif lm:
            return Ref(
                type="range",
                qualified_address=f"{sheet_name}!{cell_part}",
                sheet=sheet_name,
                cell_start=lm.group(1) + lm.group(2),
                is_cross_sheet=sheet_name != home_sheet,
            )
        else:
            col_match = re.match(r"[A-Z]+", left)
            if col_match:
                return Ref(
                    type="range",
                    qualified_address=f"{sheet_name}!{cell_part}",
                    sheet=sheet_name,
                    cell_start=col_match.group() + "1",
                    is_cross_sheet=sheet_name != home_sheet,
                )
    else:
        cm = _CELL_RE.match(cell_part)
        if cm:
            return Ref(
                type="cell",
                qualified_address=f"{sheet_name}!{cell_part}",
                sheet=sheet_name,
                cell_start=cm.group(1) + cm.group(2),
                is_cross_sheet=sheet_name != home_sheet,
            )
    return None


def _parse_local_ref(m: re.Match, home_sheet: str) -> Ref:
    """Convert a local-ref regex match to a Ref object."""
    col1 = m.group(1).upper()
    row1 = m.group(2)
    col2 = m.group(3).upper() if m.group(3) else None
    row2 = m.group(4) if m.group(4) else None

    if col2 and row2:
        return Ref(
            type="range",
            qualified_address=f"{home_sheet}!{col1}{row1}:{col2}{row2}",
            sheet=home_sheet,
            cell_start=col1 + row1,
            cell_end=col2 + row2,
            is_cross_sheet=False,
        )
    return Ref(
        type="cell",
        qualified_address=f"{home_sheet}!{col1}{row1}",
        sheet=home_sheet,
        cell_start=col1 + row1,
        is_cross_sheet=False,
    )


def parse_references(
    formula: str,
    home_sheet: str,
    named_ranges: dict[str, str] | None = None,
) -> list[Ref]:
    """Return every unique reference found in *formula*.

    If *named_ranges* is provided, named-range tokens are expanded
    to their A1 notation before parsing.
    """
    # Expand named ranges first
    expanded = formula
    if named_ranges:
        for name, ref in named_ranges.items():
            expanded = re.sub(r'\b' + re.escape(name) + r'\b', ref, expanded)

    refs: list[Ref] = []
    consumed_spans: list[tuple[int, int]] = []

    # Sheet-qualified references first
    for m in _SHEET_REF_RE.finditer(expanded):
        ref = _parse_ref_from_match(m, home_sheet)
        if ref:
            refs.append(ref)
            consumed_spans.append(m.span())

    consumed_mask: set[int] = set()
    for start, end in consumed_spans:
        consumed_mask.update(range(start, end))

    # Local (unqualified) references
    for m in _LOCAL_REF_RE.finditer(expanded):
        if any(pos in consumed_mask for pos in range(*m.span())):
            continue
        refs.append(_parse_local_ref(m, home_sheet))

    return refs


# ---------------------------------------------------------------------------
# Function & pattern extraction
# ---------------------------------------------------------------------------


def extract_functions(formula: str) -> list[str]:
    """Return sorted list of unique function names called in the formula."""
    return sorted(set(_FUNCTION_RE.findall(formula)))


def generate_pattern_id(formula: str, source_cell: str) -> tuple[str, str]:
    """Generate a pattern ID and hash by abstracting row numbers."""
    row_match = re.search(r'(\d+)$', source_cell)
    source_row = int(row_match.group(1)) if row_match else 0

    def replace_row(m: re.Match) -> str:
        row = int(m.group(2))
        if abs(row - source_row) <= 1:
            return m.group(0)[:-len(m.group(2))] + "{row}"
        return m.group(0)

    # Replace bare row numbers in cell references
    pattern = re.sub(
        r'([A-Z]+)(\d+)(?![A-Z])',
        replace_row,
        formula,
        flags=re.IGNORECASE,
    )
    # Replace absolute row references
    pattern = re.sub(
        r'\$(\d+)',
        lambda m: f"${{row}}" if abs(int(m.group(1)) - source_row) <= 1 else m.group(0),
        pattern,
    )

    pattern_hash = hashlib.sha256(pattern.encode()).hexdigest()[:8]
    return pattern, pattern_hash


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_cells(cells: list[dict[str, str]]) -> list[ParsedFormula]:
    """Parse a list of cell dicts into ParsedFormula objects.

    Each cell dict should have:
        ``sheet`` (str): Worksheet name.
        ``cell`` (str): Cell address (e.g. ``"B4"``).
        ``formula`` (str): Raw formula text, or empty string.

    Cells with empty/non-formula values are silently skipped.
    """
    parsed: list[ParsedFormula] = []

    for cell in cells:
        raw_formula = cell.get("formula", "").strip()
        if not raw_formula or not raw_formula.startswith("="):
            continue

        sheet = cell.get("sheet", "")
        cell_addr = cell.get("cell", "").upper()

        refs = parse_references(raw_formula, sheet)
        functions = extract_functions(raw_formula)
        is_array = raw_formula.startswith("={") or raw_formula.startswith("={=")
        pattern_id, pattern_hash = generate_pattern_id(raw_formula, cell_addr)

        parsed.append(ParsedFormula(
            source_sheet=sheet,
            source_cell=cell_addr,
            raw_formula=raw_formula,
            references=refs,
            functions_called=functions,
            is_array_formula=is_array,
            pattern_id=pattern_id,
            pattern_hash=pattern_hash,
        ))

    return parsed


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_dependency_artifact(
    parsed_formulas: list[ParsedFormula],
    workbook_key: str = "",
) -> dict[str, Any]:
    """Build a dependency graph artifact from parsed formulas.

    Returns a serializable dict with:
        ``workbook_key``: str
        ``summary``: dict with total_formula_cells, cross_sheet_edges, high_value_nodes
        ``nodes``: list of node dicts with id, sheet, cell, formula, node_type
        ``edges``: list of edge dicts with source, target, ref_type, is_cross_sheet
    """
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    for pf in parsed_formulas:
        target_id = f"{pf.source_sheet}!{pf.source_cell}"
        if target_id not in nodes:
            nodes[target_id] = {
                "id": target_id,
                "sheet": pf.source_sheet,
                "cell": pf.source_cell,
                "formula": pf.raw_formula,
                "node_type": "formula",
            }

        for ref in pf.references:
            if ref.type in ("cell", "range", "named_range"):
                dep_id = ref.qualified_address
                if dep_id not in nodes:
                    nodes[dep_id] = {
                        "id": dep_id,
                        "sheet": ref.sheet,
                        "cell": ref.cell_start or "",
                        "formula": "",
                        "node_type": "range" if ref.type == "range" else "data",
                    }
                if dep_id != target_id:
                    edges.append({
                        "source": dep_id,
                        "target": target_id,
                        "ref_type": ref.type,
                        "is_cross_sheet": ref.is_cross_sheet,
                    })

            elif ref.type in ("external_workbook", "importrange"):
                dep_id = f"external:{ref.qualified_address}"
                if dep_id not in nodes:
                    nodes[dep_id] = {
                        "id": dep_id,
                        "sheet": "external",
                        "cell": "",
                        "formula": "",
                        "node_type": "external",
                    }
                edges.append({
                    "source": dep_id,
                    "target": target_id,
                    "ref_type": ref.type,
                    "is_cross_sheet": True,
                })

    # Build cross-sheet edge listing for the artifact
    cross_sheet_edge_list: list[dict[str, str]] = []
    for edge in edges:
        if edge["is_cross_sheet"]:
            source_sheet = edge["source"].split("!")[0]
            target_sheet = edge["target"].split("!")[0]
            if source_sheet != target_sheet:
                cross_sheet_edge_list.append({
                    "from_sheet": source_sheet,
                    "to_sheet": target_sheet,
                })

    return {
        "workbook_key": workbook_key,
        "summary": {
            "total_formula_cells": len(parsed_formulas),
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "cross_sheet_edges": sum(1 for e in edges if e["is_cross_sheet"]),
        },
        "nodes": list(nodes.values()),
        "edges": edges,
        "cross_sheet_edges": cross_sheet_edge_list,
    }


# ---------------------------------------------------------------------------
# Signal computation
# ---------------------------------------------------------------------------


def compute_dependency_signals(
    artifact: dict[str, Any],
    high_value_threshold: int = 3,
) -> dict[str, Any]:
    """Extract actionable migration signals from a dependency artifact.

    Returns:
        ``cross_sheet_edges``: Aggregated per-sheet-pair edge weights.
        ``high_value_nodes``: Cells referenced by >= *high_value_threshold* formulas.
        ``pattern_clusters``: Formula pattern hash groupings with count.
    """
    # Cross-sheet edge aggregation
    sheet_pair_weights: dict[tuple[str, str], int] = {}
    for edge in artifact.get("edges", []):
        if not edge.get("is_cross_sheet"):
            continue
        source_sheet = edge["source"].split("!")[0]
        target_sheet = edge["target"].split("!")[0]
        if source_sheet == target_sheet:
            continue
        key = (source_sheet, target_sheet)
        sheet_pair_weights[key] = sheet_pair_weights.get(key, 0) + 1

    cross_sheet_edges = [
        {"from_sheet": k[0], "to_sheet": k[1], "weight": v}
        for k, v in sorted(sheet_pair_weights.items(), key=lambda x: x[1], reverse=True)
    ]

    # High-value nodes (cells referenced by many formulas)
    ref_count: dict[str, int] = {}
    for edge in artifact.get("edges", []):
        source = edge["source"]
        ref_count[source] = ref_count.get(source, 0) + 1

    high_value_nodes = [
        {
            "cell_id": node_id,
            "referenced_by": count,
            "sheet": node_id.split("!")[0],
        }
        for node_id, count in sorted(ref_count.items(), key=lambda x: x[1], reverse=True)
        if count >= high_value_threshold
    ]

    # Pattern clusters (from formula nodes in artifact)
    pattern_clusters: dict[str, dict] = {}
    for node in artifact.get("nodes", []):
        formula = node.get("formula", "")
        if not formula or not formula.startswith("="):
            continue
        cell = node.get("cell", "")
        sheet = node.get("sheet", "")
        _, pattern_hash = generate_pattern_id(formula, cell)
        if pattern_hash not in pattern_clusters:
            pattern_clusters[pattern_hash] = {
                "pattern_hash": pattern_hash,
                "count": 0,
                "example_formula": formula,
            }
        pattern_clusters[pattern_hash]["count"] += 1

    return {
        "cross_sheet_edges": cross_sheet_edges,
        "high_value_nodes": high_value_nodes,
        "pattern_clusters": [
            v for v in sorted(pattern_clusters.values(),
                            key=lambda x: x["count"], reverse=True)
        ],
    }
