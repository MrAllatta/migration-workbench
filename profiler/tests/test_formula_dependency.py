"""Tests for cell-level formula dependency analysis."""

import networkx as nx

from profiler.tools.formula_dependency import (
    Ref,
    ParsedFormula,
    parse_references,
    extract_functions,
    generate_pattern_id,
    parse_cells,
    build_dependency_artifact,
    compute_dependency_signals,
    build_cell_graph,
    build_sheet_dependency_graph,
    compute_sheet_signals,
    build_dependency_report,
)


def test_ref_dataclass_defaults():
    """Ref creates with correct defaults for a cell reference."""
    ref = Ref(
        type="cell",
        qualified_address="Sheet1!A1",
        sheet="Sheet1",
        cell_start="A1",
    )
    assert ref.type == "cell"
    assert ref.qualified_address == "Sheet1!A1"
    assert ref.is_cross_sheet is False
    assert ref.is_named_range is False
    assert ref.is_external is False


def test_parsed_formula_dataclass_defaults():
    """ParsedFormula creates with correct defaults."""
    pf = ParsedFormula(
        source_sheet="Sheet1",
        source_cell="B2",
        raw_formula="=SUM(A1:A10)",
    )
    assert pf.source_sheet == "Sheet1"
    assert pf.source_cell == "B2"
    assert pf.references == []
    assert pf.functions_called == []
    assert pf.is_array_formula is False


# ---------------------------------------------------------------------------
# Parsing tests
# ---------------------------------------------------------------------------


def test_parse_local_cell_reference():
    """A simple local cell ref like =A1 is parsed correctly."""
    refs = parse_references("=A1", "Sheet1")
    assert len(refs) == 1
    assert refs[0].type == "cell"
    assert refs[0].sheet == "Sheet1"
    assert refs[0].cell_start == "A1"
    assert refs[0].is_cross_sheet is False


def test_parse_cross_sheet_range():
    """A cross-sheet range like =SUM(Other!A1:B10) is parsed."""
    refs = parse_references("=SUM(Other!A1:B10)", "Sheet1")
    assert len(refs) >= 1
    range_refs = [r for r in refs if r.type == "range"]
    assert len(range_refs) >= 1
    assert range_refs[0].sheet == "Other"
    assert range_refs[0].cell_start == "A1"
    assert range_refs[0].cell_end == "B10"
    assert range_refs[0].is_cross_sheet is True


def test_parse_named_range():
    """Named range tokens are resolved before parsing."""
    refs = parse_references(
        "=SUM(myRange)", "Sheet1", named_ranges={"myRange": "Sheet1!A1:A100"}
    )
    assert len(refs) >= 1
    assert any("A1" in r.cell_start for r in refs if r.cell_start)


def test_extract_functions():
    """Function names are extracted from formula text."""
    funcs = extract_functions("=IF(A1>0, SUM(B1:B10), COUNT(C1:C10))")
    assert "IF" in funcs
    assert "SUM" in funcs
    assert "COUNT" in funcs


def test_generate_pattern_id_abstracts_row_numbers():
    """Pattern ID abstracts row numbers around the source row."""
    pattern_id, _ = generate_pattern_id("=A1+B1", "C1")
    assert "{row}" in pattern_id


def test_parse_cells_empty():
    """parse_cells returns empty list for empty input."""
    result = parse_cells([])
    assert result == []


def test_parse_cells_skips_non_formulas():
    """parse_cells skips cells without formulas."""
    cells = [
        {"sheet": "Sheet1", "cell": "A1", "formula": ""},
        {"sheet": "Sheet1", "cell": "A2", "formula": "hello"},
    ]
    result = parse_cells(cells)
    assert result == []


def test_parse_cells_parses_formula():
    """parse_cells parses a cell with a formula."""
    cells = [
        {"sheet": "Sheet1", "cell": "A1", "formula": "=SUM(B1:B10)"},
    ]
    result = parse_cells(cells)
    assert len(result) == 1
    assert result[0].source_sheet == "Sheet1"
    assert result[0].source_cell == "A1"
    assert len(result[0].references) >= 1
    assert "SUM" in result[0].functions_called


# ---------------------------------------------------------------------------
# Graph tests
# ---------------------------------------------------------------------------


def test_build_dependency_artifact_empty():
    """Empty parsed formulas produces empty artifact."""
    artifact = build_dependency_artifact([])
    assert artifact["nodes"] == []
    assert artifact["edges"] == []


def test_build_dependency_artifact_single_formula():
    """Single formula with one reference produces correct artifact."""
    cells = [
        {"sheet": "Sheet1", "cell": "B2", "formula": "=A1"},
    ]
    parsed = parse_cells(cells)
    artifact = build_dependency_artifact(parsed)
    assert len(artifact["nodes"]) == 2  # B2 (formula) + A1 (data)
    assert len(artifact["edges"]) == 1


def test_build_dependency_artifact_self_reference():
    """Self-referencing formula does not create an edge."""
    cells = [
        {"sheet": "Sheet1", "cell": "A1", "formula": "=A1"},
    ]
    parsed = parse_cells(cells)
    artifact = build_dependency_artifact(parsed)
    assert len(artifact["nodes"]) == 1
    assert len(artifact["edges"]) == 0


def test_build_dependency_artifact_cross_sheet():
    """Cross-sheet reference is flagged correctly."""
    cells = [
        {"sheet": "Summary", "cell": "C4", "formula": "=Data!A1"},
    ]
    parsed = parse_cells(cells)
    artifact = build_dependency_artifact(parsed)
    cross_sheet = artifact.get("cross_sheet_edges", [])
    assert len(cross_sheet) >= 1
    assert cross_sheet[0]["from_sheet"] == "Data"
    assert cross_sheet[0]["to_sheet"] == "Summary"


def test_compute_dependency_signals_high_value_nodes():
    """Cell referenced by multiple formulas appears as high-value."""
    cells = [
        {"sheet": "Sheet1", "cell": "B2", "formula": "=A1"},
        {"sheet": "Sheet1", "cell": "C2", "formula": "=A1"},
        {"sheet": "Sheet1", "cell": "D2", "formula": "=A1"},
    ]
    parsed = parse_cells(cells)
    artifact = build_dependency_artifact(parsed)
    signals = compute_dependency_signals(artifact)
    assert len(signals["high_value_nodes"]) >= 1
    assert signals["high_value_nodes"][0]["cell_id"] == "Sheet1!A1"
    assert signals["high_value_nodes"][0]["referenced_by"] >= 3


def test_compute_dependency_signals_pattern_clusters():
    """Formulas with same pattern are grouped."""
    cells = [
        {"sheet": "Sheet1", "cell": "A1", "formula": "=B1+C1"},
        {"sheet": "Sheet1", "cell": "A2", "formula": "=B2+C2"},
    ]
    parsed = parse_cells(cells)
    artifact = build_dependency_artifact(parsed)
    signals = compute_dependency_signals(artifact)
    # Both formulas should share the same pattern hash
    hashes = set(p.pattern_hash for p in parsed)
    assert len(hashes) == 1, f"Expected 1 pattern hash, got {hashes}"
    assert signals["pattern_clusters"][0]["count"] == 2


# ---------------------------------------------------------------------------
# build_cell_graph tests
# ---------------------------------------------------------------------------


def test_build_cell_graph_empty():
    """Empty list returns empty nx.DiGraph."""
    G = build_cell_graph([])
    assert G.number_of_nodes() == 0
    assert G.number_of_edges() == 0


def test_build_cell_graph_single_formula():
    """Single formula with one reference creates correct nodes and edges."""
    cells = [
        {"sheet": "Sheet1", "cell": "B2", "formula": "=A1"},
    ]
    parsed = parse_cells(cells)
    G = build_cell_graph(parsed)
    assert G.number_of_nodes() == 2
    assert G.number_of_edges() == 1
    assert G.nodes["Sheet1!B2"]["node_type"] == "formula"
    assert G.nodes["Sheet1!A1"]["node_type"] == "data"


def test_build_cell_graph_self_reference():
    """Self-referencing formula does not create an edge."""
    cells = [
        {"sheet": "Sheet1", "cell": "A1", "formula": "=A1"},
    ]
    parsed = parse_cells(cells)
    G = build_cell_graph(parsed)
    # Only one node (the formula cell itself) — no edge for self-ref
    assert G.number_of_nodes() == 1
    assert G.number_of_edges() == 0
    # Node exists (type is overwritten to "data" since the formula's
    # own ref re-adds the same node with node_type="data")
    assert "Sheet1!A1" in G.nodes


def test_build_cell_graph_cross_sheet():
    """Cross-sheet reference has is_cross_sheet=True on the edge."""
    cells = [
        {"sheet": "Summary", "cell": "C4", "formula": "=Data!A1"},
    ]
    parsed = parse_cells(cells)
    G = build_cell_graph(parsed)
    edges = list(G.edges(data=True))
    assert len(edges) == 1
    _, _, edge_data = edges[0]
    assert edge_data["is_cross_sheet"] is True


# ---------------------------------------------------------------------------
# build_sheet_dependency_graph tests
# ---------------------------------------------------------------------------


def test_build_sheet_graph_empty():
    """Empty cell graph produces empty sheet graph."""
    G_cell = build_cell_graph([])
    G_sheet = build_sheet_dependency_graph(G_cell)
    assert G_sheet.number_of_nodes() == 0
    assert G_sheet.number_of_edges() == 0


def test_build_sheet_graph_single_sheet():
    """All refs on same sheet produce a single node with correct counts."""
    cells = [
        {"sheet": "Sheet1", "cell": "B2", "formula": "=A1"},
        {"sheet": "Sheet1", "cell": "C2", "formula": "=B1"},
    ]
    parsed = parse_cells(cells)
    G_cell = build_cell_graph(parsed)
    G_sheet = build_sheet_dependency_graph(G_cell)
    assert G_sheet.number_of_nodes() == 1
    assert G_sheet.number_of_edges() == 0
    assert G_sheet.nodes["Sheet1"]["formula_count"] == 2
    assert G_sheet.nodes["Sheet1"]["node_count"] >= 2


def test_build_sheet_graph_cross_sheet():
    """Cross-sheet refs produce weighted edges between sheets."""
    cells = [
        {"sheet": "Summary", "cell": "C4", "formula": "=Data!A1"},
        {"sheet": "Summary", "cell": "D4", "formula": "=Data!B2"},
        {"sheet": "Data", "cell": "A1", "formula": "=Lookup!X1"},
    ]
    parsed = parse_cells(cells)
    G_cell = build_cell_graph(parsed)
    G_sheet = build_sheet_dependency_graph(G_cell)

    # Summary → Summary!C4 (formula), Summary!D4 (formula) -> 2 formulas, 2 nodes
    assert G_sheet.nodes["Summary"]["formula_count"] == 2
    assert G_sheet.nodes["Summary"]["node_count"] == 2
    # Data → Data!A1 (formula), Data!B2 (data) -> 1 formula, 2 nodes
    assert G_sheet.nodes["Data"]["formula_count"] == 1
    assert G_sheet.nodes["Data"]["node_count"] == 2
    # Lookup → Lookup!X1 (data) -> 0 formulas, 1 node
    assert G_sheet.nodes["Lookup"]["formula_count"] == 0
    assert G_sheet.nodes["Lookup"]["node_count"] == 1

    # Edge weight from Data to Summary = 2 (Data!A1→Summary!C4, Data!B2→Summary!D4)
    assert G_sheet.edges[("Data", "Summary")]["weight"] == 2
    # Edge weight from Lookup to Data = 1 (Lookup!X1→Data!A1)
    assert G_sheet.edges[("Lookup", "Data")]["weight"] == 1


# ---------------------------------------------------------------------------
# compute_sheet_signals tests
# ---------------------------------------------------------------------------


def test_compute_sheet_signals_no_orphans():
    """Sheets with cross-sheet edges are not orphaned."""
    cells = [
        {"sheet": "Summary", "cell": "C4", "formula": "=Data!A1"},
        {"sheet": "Data", "cell": "A1", "formula": "=Lookup!X1"},
    ]
    parsed = parse_cells(cells)
    G_cell = build_cell_graph(parsed)
    G_sheet = build_sheet_dependency_graph(G_cell)
    signals = compute_sheet_signals(G_cell, G_sheet)
    # All sheets with formulas (Summary, Data) have cross-sheet edges
    orphaned_sheets = {o["sheet"] for o in signals["orphaned_sheets"]}
    assert "Summary" not in orphaned_sheets
    assert "Data" not in orphaned_sheets


def test_compute_sheet_signals_orphan_detected():
    """Orphaned sheet detection — sheets with formulas but no cross-sheet edges."""
    cells = [
        # MainSheet has cross-sheet refs to OtherSheet
        {"sheet": "MainSheet", "cell": "A1", "formula": "=B1+OtherSheet!C1"},
        {"sheet": "MainSheet", "cell": "D1", "formula": "=E1"},
        # OrphanSheet has only local refs
        {"sheet": "OrphanSheet", "cell": "X1", "formula": "=Y1"},
        {"sheet": "OrphanSheet", "cell": "X2", "formula": "=Z1"},
    ]
    parsed = parse_cells(cells)
    G_cell = build_cell_graph(parsed)
    signals = compute_sheet_signals(G_cell)
    orphaned_sheets = {o["sheet"] for o in signals["orphaned_sheets"]}
    assert "OrphanSheet" in orphaned_sheets
    assert "MainSheet" not in orphaned_sheets
    assert "OtherSheet" not in orphaned_sheets


# ---------------------------------------------------------------------------
# External / IMPORTRANGE reference parsing tests
# ---------------------------------------------------------------------------


def test_parse_importrange_reference():
    """IMPORTRANGE() detected as external reference alongside regular refs."""
    refs = parse_references('=IMPORTRANGE("url", "Other!A1")+Data!B2', "Sheet1")
    importrange_refs = [r for r in refs if r.type == "importrange"]
    assert len(importrange_refs) >= 1
    assert importrange_refs[0].is_external is True
    assert importrange_refs[0].type == "importrange"
    # Also has the regular sheet-qualified ref for Data!B2
    data_refs = [r for r in refs if r.sheet == "Data"]
    assert len(data_refs) >= 1


def test_parse_external_workbook_reference():
    """External workbook bracket ref [Workbook.xlsx] is detected."""
    refs = parse_references('=[Workbook.xlsx]Sheet1!A1', "Home")
    ext_refs = [r for r in refs if r.type == "external_workbook"]
    assert len(ext_refs) >= 1
    assert ext_refs[0].type == "external_workbook"
    assert ext_refs[0].is_external is True


# ---------------------------------------------------------------------------
# Pattern → cell membership tests
# ---------------------------------------------------------------------------


def test_pattern_cluster_cells_membership():
    """Pattern clusters include cell IDs in the cells list."""
    cells = [
        {"sheet": "Sheet1", "cell": "A1", "formula": "=B1+C1"},
        {"sheet": "Sheet1", "cell": "A2", "formula": "=B2+C2"},
    ]
    parsed = parse_cells(cells)
    artifact = build_dependency_artifact(parsed)
    signals = compute_dependency_signals(artifact)
    cluster = signals["pattern_clusters"][0]
    assert "cells" in cluster
    assert len(cluster["cells"]) == 2
    assert "Sheet1!A1" in cluster["cells"]
    assert "Sheet1!A2" in cluster["cells"]
    # Also verify other expected keys
    assert "pattern_hash" in cluster
    assert "count" in cluster
    assert cluster["count"] == 2
    assert "example_formula" in cluster


# ---------------------------------------------------------------------------
# Artifact new-key tests
# ---------------------------------------------------------------------------


def test_artifact_has_sheet_graph_key():
    """Dependency artifact includes sheet_graph with nodes and edges."""
    cells = [
        {"sheet": "Sheet1", "cell": "B2", "formula": "=Data!A1"},
    ]
    parsed = parse_cells(cells)
    artifact = build_dependency_artifact(parsed)
    assert "sheet_graph" in artifact
    sg = artifact["sheet_graph"]
    assert "nodes" in sg
    assert "edges" in sg
    assert len(sg["nodes"]) >= 1
    node = sg["nodes"][0]
    assert "id" in node
    assert "formula_count" in node
    assert "node_count" in node


def test_artifact_has_sheet_signals_key():
    """Artifact includes sheet_signals with orphaned_sheets."""
    cells = [
        {"sheet": "Sheet1", "cell": "B2", "formula": "=Data!A1"},
    ]
    parsed = parse_cells(cells)
    artifact = build_dependency_artifact(parsed)
    assert "sheet_signals" in artifact
    ss = artifact["sheet_signals"]
    assert "orphaned_sheets" in ss


def test_artifact_has_report_key():
    """Artifact includes report with all 7 expected sections."""
    cells = [
        {"sheet": "Sheet1", "cell": "B2", "formula": "=Data!A1"},
    ]
    parsed = parse_cells(cells)
    artifact = build_dependency_artifact(parsed)
    assert "report" in artifact
    report = artifact["report"]
    expected_sections = [
        "formula_totals",
        "external_references",
        "high_value_nodes",
        "top_most_referenced",
        "orphaned_sheets",
        "sheet_dependency_table",
        "pattern_clusters",
    ]
    for section in expected_sections:
        assert section in report, f"Missing report section: {section}"


def test_artifact_has_cross_workbook_deps():
    """Summary includes cross_workbook_deps with expected sub-keys."""
    cells = [
        {"sheet": "Sheet1", "cell": "B2", "formula": "=Data!A1"},
    ]
    parsed = parse_cells(cells)
    artifact = build_dependency_artifact(parsed)
    summary = artifact["summary"]
    assert "cross_workbook_deps" in summary
    cwd = summary["cross_workbook_deps"]
    assert "workbook_key" in cwd
    assert "external_ref_count" in cwd
    assert "importrange_count" in cwd


def test_report_top_most_referenced():
    """Report includes top_most_referenced list sorted by out-degree."""
    cells = [
        {"sheet": "Sheet1", "cell": "B1", "formula": "=A1"},
        {"sheet": "Sheet1", "cell": "B2", "formula": "=A1"},
        {"sheet": "Sheet1", "cell": "B3", "formula": "=A1"},
        {"sheet": "Sheet1", "cell": "C1", "formula": "=A2"},
    ]
    parsed = parse_cells(cells)
    artifact = build_dependency_artifact(parsed)
    report = artifact["report"]
    assert "top_most_referenced" in report
    assert len(report["top_most_referenced"]) > 0
    # Verify sorted by out_degree descending
    top = report["top_most_referenced"]
    for i in range(len(top) - 1):
        assert top[i]["out_degree"] >= top[i + 1]["out_degree"]
    # Sheet1!A1 should be most referenced (3 formulas reference it)
    assert top[0]["cell_id"] == "Sheet1!A1"
    assert top[0]["out_degree"] >= 3


# ---------------------------------------------------------------------------
# Backwards compatibility tests
# ---------------------------------------------------------------------------


def test_build_dependency_artifact_still_returns_old_keys():
    """Existing consumers still get the original keys unchanged."""
    cells = [
        {"sheet": "Sheet1", "cell": "B2", "formula": "=A1"},
    ]
    parsed = parse_cells(cells)
    artifact = build_dependency_artifact(parsed)
    # Old keys must still be present
    assert "workbook_key" in artifact
    assert "summary" in artifact
    assert "nodes" in artifact
    assert "edges" in artifact
    assert "cross_sheet_edges" in artifact
    # Nodes and edges have the same format as before
    assert len(artifact["nodes"]) >= 1
    assert "id" in artifact["nodes"][0]
    assert len(artifact["edges"]) >= 1
    assert "source" in artifact["edges"][0]
    assert "target" in artifact["edges"][0]
