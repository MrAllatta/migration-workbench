"""Tests for cell-level formula dependency analysis."""

from profiler.tools.formula_dependency import (
    Ref,
    ParsedFormula,
    parse_references,
    extract_functions,
    generate_pattern_id,
    parse_cells,
    build_dependency_artifact,
    compute_dependency_signals,
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
