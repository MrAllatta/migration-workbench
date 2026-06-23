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

import networkx as nx


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
_IMPORTRANGE_FULL_RE = re.compile(
    r'IMPORTRANGE\s*\([^)]*\)',
    re.IGNORECASE,
)
_IMPORTRANGE_ARGS_RE = re.compile(
    r'IMPORTRANGE\s*\(\s*"([^"]+)"',
    re.IGNORECASE,
)
_EXTERNAL_REF_RE = re.compile(r'\[.+?\]')
_EXTERNAL_WB_RE = re.compile(r'\[([^\]]+)\]')

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


def _add_importrange_ref(
    refs: list[Ref], consumed_spans: list[tuple[int, int]], match: re.Match
) -> None:
    """Parse an IMPORTRANGE match into a Ref and track its consumed span."""
    key_m = _IMPORTRANGE_ARGS_RE.search(match.group(0))
    spreadsheet_key = key_m.group(1) if key_m else ""
    refs.append(Ref(
        type="importrange",
        qualified_address=f"IMPORTRANGE({spreadsheet_key})",
        sheet="external",
        cell_start=None,
        is_cross_sheet=True,
        is_external=True,
        external_spreadsheet_id=spreadsheet_key,
    ))
    consumed_spans.append(match.span())


def _add_external_wb_ref(
    refs: list[Ref], consumed_spans: list[tuple[int, int]], match: re.Match
) -> None:
    """Parse an external workbook bracket match into a Ref and track span."""
    refs.append(Ref(
        type="external_workbook",
        qualified_address=match.group(0),
        sheet="external",
        cell_start=None,
        is_cross_sheet=True,
        is_external=True,
        external_spreadsheet_id=match.group(1),
    ))
    consumed_spans.append(match.span())


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

    # 1. IMPORTRANGE first — mark entire call as consumed so nested
    #    range strings (e.g. "Data!A1") are not double-parsed.
    for m in _IMPORTRANGE_FULL_RE.finditer(expanded):
        _add_importrange_ref(refs, consumed_spans, m)

    # 2. Bracket-style external workbook references [Workbook.xlsx]
    consumed_mask: set[int] = set()
    for start, end in consumed_spans:
        consumed_mask.update(range(start, end))
    for m in _EXTERNAL_WB_RE.finditer(expanded):
        if any(pos in consumed_mask for pos in range(*m.span())):
            continue
        _add_external_wb_ref(refs, consumed_spans, m)

    # 3. Rebuild mask and parse sheet-qualified references
    consumed_mask = set()
    for start, end in consumed_spans:
        consumed_mask.update(range(start, end))
    for m in _SHEET_REF_RE.finditer(expanded):
        if any(pos in consumed_mask for pos in range(*m.span())):
            continue
        ref = _parse_ref_from_match(m, home_sheet)
        if ref:
            refs.append(ref)
            consumed_spans.append(m.span())

    # 4. Local (unqualified) references
    consumed_mask = set()
    for start, end in consumed_spans:
        consumed_mask.update(range(start, end))
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
# Graph builder — cell-level
# ---------------------------------------------------------------------------


def build_cell_graph(parsed_formulas: list[ParsedFormula]) -> nx.DiGraph:
    """Build an nx.DiGraph from parsed formulas.

    Nodes are ``{sheet}!{cell}`` with attributes:
        ``node_type``: "formula", "data", "range", or "external"
        ``sheet``: sheet name
        ``cell``: cell address
        ``formula``: raw formula text (empty for non-formula nodes)

    Edges go from referenced cell → formula cell with attributes:
        ``ref_type``: "cell", "range", "importrange", "external_workbook"
        ``is_cross_sheet``: bool

    Self-references do NOT create edges.
    """
    G = nx.DiGraph()

    for pf in parsed_formulas:
        target_id = f"{pf.source_sheet}!{pf.source_cell}"
        G.add_node(
            target_id,
            node_type="formula",
            sheet=pf.source_sheet,
            cell=pf.source_cell,
            formula=pf.raw_formula,
        )

        for ref in pf.references:
            if ref.type in ("cell", "range", "named_range"):
                dep_id = ref.qualified_address
                node_type = "range" if ref.type == "range" else "data"
                G.add_node(
                    dep_id,
                    node_type=node_type,
                    sheet=ref.sheet,
                    cell=ref.cell_start or "",
                    formula="",
                )
                if dep_id != target_id:
                    G.add_edge(
                        dep_id,
                        target_id,
                        ref_type=ref.type,
                        is_cross_sheet=ref.is_cross_sheet,
                    )

            elif ref.type in ("external_workbook", "importrange"):
                dep_id = f"external:{ref.qualified_address}"
                G.add_node(
                    dep_id,
                    node_type="external",
                    sheet="external",
                    cell="",
                    formula="",
                )
                G.add_edge(
                    dep_id,
                    target_id,
                    ref_type=ref.type,
                    is_cross_sheet=True,
                )

    return G


def _serialize_cell_graph(G: nx.DiGraph) -> tuple[list[dict], list[dict]]:
    """Convert nx.DiGraph to node/edge dict lists matching the artifact format."""
    nodes_list: list[dict[str, Any]] = []
    for node_id, data in G.nodes(data=True):
        entry: dict[str, Any] = {"id": node_id}
        entry.update(data)
        nodes_list.append(entry)

    edges_list: list[dict[str, Any]] = []
    for u, v, data in G.edges(data=True):
        entry: dict[str, Any] = {"source": u, "target": v}
        entry.update(data)
        edges_list.append(entry)

    return nodes_list, edges_list


def _compute_cross_sheet_edges_list(
    edges_list: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Build the cross_sheet_edges listing for the artifact."""
    cross_sheet_edge_list: list[dict[str, str]] = []
    for edge in edges_list:
        if edge.get("is_cross_sheet"):
            source_sheet = edge["source"].split("!")[0]
            target_sheet = edge["target"].split("!")[0]
            if source_sheet != target_sheet:
                cross_sheet_edge_list.append({
                    "from_sheet": source_sheet,
                    "to_sheet": target_sheet,
                })
    return cross_sheet_edge_list


# ---------------------------------------------------------------------------
# Graph builder — sheet-level
# ---------------------------------------------------------------------------


def build_sheet_dependency_graph(G_cell: nx.DiGraph) -> nx.DiGraph:
    """Collapse cell-level dependency graph to a sheet-level graph.

    Nodes are sheet names annotated with ``formula_count`` and ``node_count``.
    Edges are sheet → sheet with ``weight`` = count of distinct cell-level
    cross-sheet edges.

    Mirrors gsheet-analyzer's ``builders/sheet_graph.py``.
    """
    SG = nx.DiGraph()

    formula_count: dict[str, int] = {}
    node_count: dict[str, int] = {}

    for node_id, data in G_cell.nodes(data=True):
        sheet = node_id.split("!")[0]
        node_count[sheet] = node_count.get(sheet, 0) + 1
        if data.get("node_type") == "formula":
            formula_count[sheet] = formula_count.get(sheet, 0) + 1

    for sheet in node_count:
        SG.add_node(
            sheet,
            formula_count=formula_count.get(sheet, 0),
            node_count=node_count[sheet],
        )

    weights: dict[tuple[str, str], int] = {}
    for u, v in G_cell.edges():
        u_sheet = u.split("!")[0]
        v_sheet = v.split("!")[0]
        if u_sheet != v_sheet:
            key = (u_sheet, v_sheet)
            weights[key] = weights.get(key, 0) + 1

    for (src, dst), w in weights.items():
        SG.add_edge(src, dst, weight=w)

    return SG


# ---------------------------------------------------------------------------
# Cross-workbook dependency helpers
# ---------------------------------------------------------------------------


def _extract_cross_workbook_deps(
    parsed_formulas: list[ParsedFormula],
) -> list[dict[str, Any]]:
    """Extract external/IMPORTRANGE dependency records."""
    deps: list[dict[str, Any]] = []
    for pf in parsed_formulas:
        for ref in pf.references:
            if ref.type in ("external_workbook", "importrange"):
                deps.append({
                    "sheet": pf.source_sheet,
                    "cell": pf.source_cell,
                    "formula": pf.raw_formula,
                    "ref_type": ref.type,
                    "external_id": ref.external_spreadsheet_id or "",
                    "qualified_address": ref.qualified_address,
                })
    return deps


# ---------------------------------------------------------------------------
# Artifact builder
# ---------------------------------------------------------------------------


def build_dependency_artifact(
    parsed_formulas: list[ParsedFormula],
    workbook_key: str = "",
) -> dict[str, Any]:
    """Build a dependency graph artifact from parsed formulas.

    Internally uses ``build_cell_graph()`` and ``build_sheet_dependency_graph()``
    to construct an nx.DiGraph, then serializes to a dict for downstream
    consumers.

    Returns a serializable dict with:
        ``workbook_key``: str
        ``summary``: dict with totals, cross-workbook deps
        ``nodes``: list of node dicts
        ``edges``: list of edge dicts
        ``cross_sheet_edges``: list of per-sheet-pair edges
        ``sheet_graph``: serialized sheet-level graph
        ``sheet_signals``: orphaned-sheet detection
        ``report``: structured dependency report
    """
    G_cell = build_cell_graph(parsed_formulas)
    nodes_list, edges_list = _serialize_cell_graph(G_cell)

    cross_sheet_edge_list = _compute_cross_sheet_edges_list(edges_list)

    # Cross-workbook deps
    cross_workbook_deps = _extract_cross_workbook_deps(parsed_formulas)
    external_ref_count = sum(
        1 for d in cross_workbook_deps if d["ref_type"] == "external_workbook"
    )
    importrange_count = sum(
        1 for d in cross_workbook_deps if d["ref_type"] == "importrange"
    )

    # Sheet-level graph
    G_sheet = build_sheet_dependency_graph(G_cell)
    sheet_nodes: list[dict[str, Any]] = []
    for sheet_name, data in G_sheet.nodes(data=True):
        entry: dict[str, Any] = {"id": sheet_name}
        entry.update(data)
        sheet_nodes.append(entry)
    sheet_edges: list[dict[str, Any]] = []
    for u, v, data in G_sheet.edges(data=True):
        entry: dict[str, Any] = {"from_sheet": u, "to_sheet": v}
        entry.update(data)
        sheet_edges.append(entry)

    # Signals
    signals = compute_dependency_signals(
        {"nodes": nodes_list, "edges": edges_list}, cell_graph=G_cell
    )
    sheet_signals = compute_sheet_signals(G_cell, G_sheet)

    artifact: dict[str, Any] = {
        "workbook_key": workbook_key,
        "summary": {
            "total_formula_cells": len(parsed_formulas),
            "total_nodes": G_cell.number_of_nodes(),
            "total_edges": G_cell.number_of_edges(),
            "cross_sheet_edges": sum(
                1 for e in edges_list if e.get("is_cross_sheet")
            ),
            "cross_workbook_deps": {
                "workbook_key": workbook_key,
                "external_ref_count": external_ref_count,
                "importrange_count": importrange_count,
            },
        },
        "nodes": nodes_list,
        "edges": edges_list,
        "cross_sheet_edges": cross_sheet_edge_list,
        "sheet_graph": {
            "nodes": sheet_nodes,
            "edges": sheet_edges,
        },
        "sheet_signals": sheet_signals,
    }

    # Report aggregates all signals into a structured summary
    artifact["report"] = build_dependency_report(artifact)
    return artifact


# ---------------------------------------------------------------------------
# Signal computation — dependency signals
# ---------------------------------------------------------------------------


def _rebuild_graph_from_artifact(artifact: dict[str, Any]) -> nx.DiGraph:
    """Rebuild an nx.DiGraph from the serialized nodes/edges in an artifact."""
    G = nx.DiGraph()
    for node in artifact.get("nodes", []):
        node_id = node["id"]
        attrs = {k: v for k, v in node.items() if k != "id"}
        G.add_node(node_id, **attrs)
    for edge in artifact.get("edges", []):
        G.add_edge(edge["source"], edge["target"],
                   ref_type=edge.get("ref_type", ""),
                   is_cross_sheet=edge.get("is_cross_sheet", False))
    return G


def compute_dependency_signals(
    artifact: dict[str, Any],
    high_value_threshold: int = 3,
    cell_graph: nx.DiGraph | None = None,
) -> dict[str, Any]:
    """Extract actionable migration signals from a dependency artifact.

    If *cell_graph* is provided, signals are computed from the graph
    directly; otherwise the graph is rebuilt from the artifact's node
    and edge lists.

    Returns:
        ``cross_sheet_edges``: Aggregated per-sheet-pair edge weights.
        ``high_value_nodes``: Cells referenced by >= *high_value_threshold* formulas.
        ``pattern_clusters``: Formula pattern hash groupings with count and cells.
    """
    G = cell_graph if cell_graph is not None else _rebuild_graph_from_artifact(artifact)

    # Cross-sheet edge aggregation from graph
    sheet_pair_weights: dict[tuple[str, str], int] = {}
    for u, v, data in G.edges(data=True):
        if not data.get("is_cross_sheet"):
            continue
        u_sheet = u.split("!")[0]
        v_sheet = v.split("!")[0]
        if u_sheet == v_sheet:
            continue
        key = (u_sheet, v_sheet)
        sheet_pair_weights[key] = sheet_pair_weights.get(key, 0) + 1

    cross_sheet_edges = [
        {"from_sheet": k[0], "to_sheet": k[1], "weight": v}
        for k, v in sorted(sheet_pair_weights.items(), key=lambda x: x[1], reverse=True)
    ]

    # High-value nodes via out_degree (edges from referenced → formula)
    # out_degree counts how many formulas reference each node
    ref_count: dict[str, int] = dict(G.out_degree())

    high_value_nodes = [
        {
            "cell_id": node_id,
            "referenced_by": count,
            "sheet": node_id.split("!")[0],
        }
        for node_id, count in sorted(ref_count.items(), key=lambda x: x[1], reverse=True)
        if count >= high_value_threshold
    ]

    # Pattern clusters with cell membership
    pattern_clusters: dict[str, dict] = {}
    for node_id, data in G.nodes(data=True):
        formula = data.get("formula", "")
        if not formula or not formula.startswith("="):
            continue
        cell = data.get("cell", "")
        _, pattern_hash = generate_pattern_id(formula, cell)
        if pattern_hash not in pattern_clusters:
            pattern_clusters[pattern_hash] = {
                "pattern_hash": pattern_hash,
                "count": 0,
                "example_formula": formula,
                "cells": [],
            }
        pattern_clusters[pattern_hash]["count"] += 1
        pattern_clusters[pattern_hash]["cells"].append(node_id)

    return {
        "cross_sheet_edges": cross_sheet_edges,
        "high_value_nodes": high_value_nodes,
        "pattern_clusters": [
            v for v in sorted(pattern_clusters.values(),
                            key=lambda x: x["count"], reverse=True)
        ],
    }


# ---------------------------------------------------------------------------
# Signal computation — sheet signals
# ---------------------------------------------------------------------------


def compute_sheet_signals(
    G_cell: nx.DiGraph,
    G_sheet: nx.DiGraph | None = None,
) -> dict[str, Any]:
    """Detect orphaned sheets — sheets with formulas but no cross-sheet edges.

    Args:
        G_cell: Cell-level dependency graph.
        G_sheet: Sheet-level graph (if already computed). If ``None``,
                 membership is derived from *G_cell* directly.

    Returns:
        dict with ``orphaned_sheets`` list.
    """
    # Collect all sheets from the cell graph
    sheet_formula_count: dict[str, int] = {}
    for node_id, data in G_cell.nodes(data=True):
        sheet = node_id.split("!")[0]
        if data.get("node_type") == "formula":
            sheet_formula_count[sheet] = sheet_formula_count.get(sheet, 0) + 1

    # Determine which sheets participate in cross-sheet edges
    sheets_with_cross_sheet_edges: set[str] = set()
    for u, v, data in G_cell.edges(data=True):
        if data.get("is_cross_sheet"):
            sheets_with_cross_sheet_edges.add(u.split("!")[0])
            sheets_with_cross_sheet_edges.add(v.split("!")[0])

    orphaned: list[dict[str, Any]] = []
    for sheet, formula_count in sheet_formula_count.items():
        if sheet not in sheets_with_cross_sheet_edges:
            orphaned.append({
                "sheet": sheet,
                "formula_count": formula_count,
            })

    return {
        "orphaned_sheets": orphaned,
    }


# ---------------------------------------------------------------------------
# Report aggregation
# ---------------------------------------------------------------------------


def _get_cell_graph_referenced_nodes(G: nx.DiGraph) -> list[dict[str, Any]]:
    """Return in-degree (node referenced by X formulas) for every node."""
    result: list[dict[str, Any]] = []
    for node_id in G.nodes():
        in_deg = G.in_degree(node_id)
        out_deg = G.out_degree(node_id)
        if in_deg > 0 or out_deg > 0:
            sheet = node_id.split("!")[0]
            result.append({
                "cell_id": node_id,
                "sheet": sheet,
                "in_degree": in_deg,
                "out_degree": out_deg,
            })
    return result


def build_dependency_report(artifact: dict[str, Any]) -> dict[str, Any]:
    """Build a structured report from the dependency artifact.

    Sections:
        - ``formula_totals``: aggregate counts
        - ``external_references``: list of external/IMPORTRANGE refs
        - ``high_value_nodes``: from compute_dependency_signals
        - ``top_most_referenced``: top 10 nodes by in-degree
        - ``orphaned_sheets``: from sheet_signals
        - ``sheet_dependency_table``: sheet-graph edges sorted by weight desc
        - ``pattern_clusters``: from compute_dependency_signals
    """
    summary = artifact.get("summary", {})
    signals = compute_dependency_signals(artifact)

    # Top 10 most-referenced nodes from the cell graph
    G = _rebuild_graph_from_artifact(artifact)
    referenced_nodes = _get_cell_graph_referenced_nodes(G)
    top_most_referenced = sorted(
        referenced_nodes, key=lambda x: x["out_degree"], reverse=True
    )[:10]

    formula_totals = {
        "total_formula_cells": summary.get("total_formula_cells", 0),
        "total_nodes": summary.get("total_nodes", 0),
        "total_edges": summary.get("total_edges", 0),
        "cross_sheet_edges": summary.get("cross_sheet_edges", 0),
        "worksheets_with_formulas": sum(
            1 for node, data in G.nodes(data=True)
            if data.get("node_type") == "formula"
        ),
    }

    # External references
    external_references: list[dict[str, Any]] = []
    workbook_key = artifact.get("workbook_key", "")
    cross_wb = summary.get("cross_workbook_deps", {})
    if cross_wb.get("importrange_count", 0) > 0 or cross_wb.get("external_ref_count", 0) > 0:
        for node_id, data in G.nodes(data=True):
            if data.get("node_type") == "external":
                external_references.append({
                    "cell_id": node_id,
                    "sheet": data.get("sheet", ""),
                    "formula": data.get("formula", ""),
                })

    # Sheet dependency table from sheet_graph
    sheet_graph = artifact.get("sheet_graph", {})
    sheet_dep_edges = sorted(
        sheet_graph.get("edges", []),
        key=lambda e: e.get("weight", 0),
        reverse=True,
    )

    sheet_signals = artifact.get("sheet_signals", {})

    return {
        "formula_totals": formula_totals,
        "external_references": external_references,
        "high_value_nodes": signals.get("high_value_nodes", []),
        "top_most_referenced": top_most_referenced,
        "orphaned_sheets": sheet_signals.get("orphaned_sheets", []),
        "sheet_dependency_table": sheet_dep_edges,
        "pattern_clusters": signals.get("pattern_clusters", []),
    }
