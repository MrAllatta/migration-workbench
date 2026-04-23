"""Pull formulas, values, notes, and data-validation rules for a single Google
Sheets tab (or list the tabs of a workbook).

This is a read-only inspection tool for tracing spreadsheet logic. It
intentionally does NOT feed the importer pipeline. It reuses the existing
credentials helper from the app's Google Sheets connector.

Usage examples (run from repo root after `source .venv/bin/activate` and
exporting .env so GOOGLE_APPLICATION_CREDENTIALS is set):

    python scripts/inspect_sheet_formulas.py \
        --spreadsheet-id 1mM9pkhqmmU9ze1M5_tBoZeA8zfuGiJv8YdXdFAh1xi4

    python scripts/inspect_sheet_formulas.py \
        --spreadsheet-id 1mM9pkhqmmU9ze1M5_tBoZeA8zfuGiJv8YdXdFAh1xi4 \
        --tab "Harvest Plan 401+402+801" \
        --out scripts/_out/302-harvest-plan.json

Outputs (when --tab is given):
    <out>.json   — structured dump of the tab
    <out>.md     — short human-readable summary (sheets, row/col counts,
                    unique formula skeletons, data validation rules)
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from connectors.google_sheets import (
    DRIVE_READONLY_SCOPE,
    SHEETS_READONLY_SCOPE,
    build_google_service,
    extract_spreadsheet_id,
)


def _col_letter(idx0: int) -> str:
    """0-indexed column number -> A, B, ..., Z, AA, AB, ..."""
    n = idx0 + 1
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def list_tabs(sheets_service, spreadsheet_id: str) -> list[dict]:
    response = (
        sheets_service.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            fields="properties(title),sheets(properties(sheetId,title,index,gridProperties))",
        )
        .execute()
    )
    return [
        {
            "title": s["properties"]["title"],
            "sheet_id": s["properties"]["sheetId"],
            "index": s["properties"].get("index"),
            "rows": s["properties"].get("gridProperties", {}).get("rowCount"),
            "cols": s["properties"].get("gridProperties", {}).get("columnCount"),
        }
        for s in response.get("sheets", [])
    ]


def fetch_tab_grid(sheets_service, spreadsheet_id: str, tab_title: str) -> dict:
    """Return one sheet's grid with formulas, effective values, formatted values,
    notes, and data validation."""
    fields = (
        "properties(title),"
        "sheets(properties(sheetId,title,gridProperties),"
        "data(startRow,startColumn,rowData(values("
        "formattedValue,userEnteredValue,effectiveValue,note,dataValidation"
        "))))"
    )
    range_ = f"'{tab_title.replace(chr(39), chr(39)*2)}'"
    response = (
        sheets_service.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            ranges=[range_],
            includeGridData=True,
            fields=fields,
        )
        .execute()
    )
    return response


def _user_entered_repr(ue: dict | None) -> tuple[str, str]:
    """Return (kind, text) for userEnteredValue."""
    if not ue:
        return ("empty", "")
    if "formulaValue" in ue:
        return ("formula", ue["formulaValue"])
    for k in ("stringValue", "numberValue", "boolValue", "errorValue"):
        if k in ue:
            val = ue[k]
            if isinstance(val, dict):
                val = val.get("message", str(val))
            return (k.replace("Value", ""), str(val))
    return ("empty", "")


FORMULA_SKELETON_RE = re.compile(r"'[^']*'!|\b[A-Z]+\d+(?::[A-Z]+\d+)?|\b[A-Z]+:[A-Z]+\b|\b\d+(?:\.\d+)?\b")


def formula_skeleton(formula: str) -> str:
    """Replace specific ranges/numbers with placeholders so formulas that
    only differ in the row number collapse into the same skeleton."""
    text = formula
    text = re.sub(r"'([^']*)'!", lambda m: f"'{m.group(1)}'!", text)  # keep sheet refs
    text = re.sub(r"\$?[A-Z]+\$?\d+(?::\$?[A-Z]+\$?\d+)?", "<RANGE>", text)
    text = re.sub(r"\$?[A-Z]+:\$?[A-Z]+", "<COLRANGE>", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\b", "<N>", text)
    return text


SHEET_REF_RE = re.compile(r"'([^']+)'!|\b([A-Za-z_][A-Za-z0-9_]*)!")
IMPORTRANGE_RE = re.compile(r"IMPORTRANGE\s*\(\s*\"([^\"]+)\"\s*,\s*\"([^\"]+)\"", re.IGNORECASE)
FUNCTION_RE = re.compile(r"\b([A-Z][A-Z0-9_\.]*)\s*\(")


def extract_references(formula: str) -> dict:
    sheet_refs = set()
    for m in SHEET_REF_RE.finditer(formula):
        sheet_refs.add(m.group(1) or m.group(2))
    import_ranges = [{"spreadsheet": a, "range": b} for a, b in IMPORTRANGE_RE.findall(formula)]
    functions = sorted({m.group(1) for m in FUNCTION_RE.finditer(formula)})
    return {
        "functions": functions,
        "sheet_refs": sorted(sheet_refs),
        "import_ranges": import_ranges,
    }


def summarize_tab(tab_payload: dict, focus_col_letter: str | None = None) -> dict:
    workbook_title = tab_payload.get("properties", {}).get("title")
    sheet = tab_payload["sheets"][0]
    props = sheet["properties"]
    data_blocks = sheet.get("data", [])

    # Flatten row data across data blocks (usually 1 block for a full-tab range).
    cells: list[dict] = []  # {row, col, kind, text, note, dv}
    for block in data_blocks:
        start_row = block.get("startRow", 0)
        start_col = block.get("startColumn", 0)
        for r_off, row in enumerate(block.get("rowData", [])):
            for c_off, cell in enumerate(row.get("values", []) or []):
                kind, text = _user_entered_repr(cell.get("userEnteredValue"))
                formatted = cell.get("formattedValue", "")
                note = cell.get("note")
                dv = cell.get("dataValidation")
                cells.append({
                    "row": start_row + r_off + 1,
                    "col": start_col + c_off,
                    "col_letter": _col_letter(start_col + c_off),
                    "kind": kind,
                    "user_entered": text,
                    "formatted": formatted,
                    "note": note,
                    "data_validation": dv,
                })

    formulas = [c for c in cells if c["kind"] == "formula"]

    skeleton_counts: Counter = Counter()
    func_counts: Counter = Counter()
    sheet_ref_counts: Counter = Counter()
    import_ranges: list[dict] = []
    for c in formulas:
        sk = formula_skeleton(c["user_entered"])
        skeleton_counts[sk] += 1
        info = extract_references(c["user_entered"])
        for f in info["functions"]:
            func_counts[f] += 1
        for s in info["sheet_refs"]:
            sheet_ref_counts[s] += 1
        for ir in info["import_ranges"]:
            import_ranges.append(ir)

    dv_rules: list[dict] = []
    seen_dv_sig: set[str] = set()
    for c in cells:
        dv = c.get("data_validation")
        if not dv:
            continue
        sig = json.dumps(dv, sort_keys=True)
        if sig in seen_dv_sig:
            continue
        seen_dv_sig.add(sig)
        dv_rules.append({
            "example_cell": f"{c['col_letter']}{c['row']}",
            "rule": dv,
        })

    focus = None
    if focus_col_letter:
        focus_cells = [c for c in cells if c["col_letter"] == focus_col_letter]
        focus = {
            "col_letter": focus_col_letter,
            "count": len(focus_cells),
            "header": next((c for c in focus_cells if c["row"] == 1), None),
            "first_20": focus_cells[:20],
            "unique_kinds": dict(Counter(c["kind"] for c in focus_cells)),
            "unique_formula_skeletons": Counter(
                formula_skeleton(c["user_entered"]) for c in focus_cells if c["kind"] == "formula"
            ).most_common(),
            "distinct_data_validation": [
                {"example_cell": f"{c['col_letter']}{c['row']}", "rule": c["data_validation"]}
                for i, c in enumerate(focus_cells)
                if c.get("data_validation")
                and json.dumps(c["data_validation"], sort_keys=True)
                not in {
                    json.dumps(focus_cells[j]["data_validation"], sort_keys=True)
                    for j in range(i)
                    if focus_cells[j].get("data_validation")
                }
            ],
        }

    return {
        "workbook_title": workbook_title,
        "tab_title": props.get("title"),
        "grid": {
            "rows": props.get("gridProperties", {}).get("rowCount"),
            "cols": props.get("gridProperties", {}).get("columnCount"),
        },
        "cell_count": len(cells),
        "formula_cell_count": len(formulas),
        "unique_formula_skeletons": skeleton_counts.most_common(),
        "functions_used": func_counts.most_common(),
        "cross_sheet_refs": sheet_ref_counts.most_common(),
        "importranges": import_ranges,
        "data_validation_rules": dv_rules,
        "focus_column": focus,
    }


def render_markdown(summary: dict) -> str:
    lines = []
    lines.append(f"# {summary['workbook_title']} / {summary['tab_title']}")
    lines.append("")
    g = summary["grid"]
    lines.append(f"Grid: {g['rows']} rows x {g['cols']} cols  |  "
                 f"non-empty cells: {summary['cell_count']}  |  "
                 f"formula cells: {summary['formula_cell_count']}")
    lines.append("")
    lines.append("## Cross-sheet references (within workbook)")
    for name, n in summary["cross_sheet_refs"]:
        lines.append(f"- `{name}`: {n} refs")
    lines.append("")
    if summary["importranges"]:
        lines.append("## IMPORTRANGE targets (external workbooks)")
        for ir in summary["importranges"]:
            lines.append(f"- `{ir['spreadsheet']}` :: `{ir['range']}`")
        lines.append("")
    lines.append("## Functions used")
    lines.append(", ".join(f"{fn}({n})" for fn, n in summary["functions_used"]))
    lines.append("")
    lines.append("## Top formula skeletons (row refs collapsed to <RANGE>)")
    for sk, n in summary["unique_formula_skeletons"][:30]:
        lines.append(f"- ({n}x) `{sk}`")
    lines.append("")
    if summary["data_validation_rules"]:
        lines.append("## Data validation rules on this tab")
        for rule in summary["data_validation_rules"]:
            lines.append(f"- example cell: `{rule['example_cell']}`")
            lines.append(f"  rule: `{json.dumps(rule['rule'])}`")
        lines.append("")
    focus = summary.get("focus_column")
    if focus:
        lines.append(f"## Focus column: {focus['col_letter']} (count={focus['count']})")
        header = focus.get("header")
        if header:
            lines.append(f"- header: `{header.get('formatted') or header.get('user_entered')}`")
        lines.append(f"- kinds: {focus['unique_kinds']}")
        if focus["unique_formula_skeletons"]:
            lines.append("- formula skeletons:")
            for sk, n in focus["unique_formula_skeletons"]:
                lines.append(f"  - ({n}x) `{sk}`")
        if focus["distinct_data_validation"]:
            lines.append("- data validation (column scope):")
            for rule in focus["distinct_data_validation"]:
                lines.append(f"  - example `{rule['example_cell']}`: `{json.dumps(rule['rule'])}`")
        lines.append("- first 20 cells:")
        for c in focus["first_20"]:
            display = c.get("formatted") or c.get("user_entered")
            note = f"  (note: {c['note']!r})" if c.get("note") else ""
            lines.append(f"  - {c['col_letter']}{c['row']}  [{c['kind']}]  {display!r}{note}")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spreadsheet-id", required=True, help="Spreadsheet id or URL")
    parser.add_argument("--tab", help="Worksheet (tab) title. If omitted, list tabs and exit.")
    parser.add_argument("--focus-col", default=None, help="Column letter to trace (e.g. B)")
    parser.add_argument("--out", default=None, help="Output JSON path; .md summary is also written next to it")
    args = parser.parse_args()

    spreadsheet_id = extract_spreadsheet_id(args.spreadsheet_id)
    drive_scopes = [SHEETS_READONLY_SCOPE, DRIVE_READONLY_SCOPE]
    sheets_service = build_google_service("sheets", "v4", drive_scopes)

    if not args.tab:
        tabs = list_tabs(sheets_service, spreadsheet_id)
        for t in tabs:
            print(f"[{t['index']:>2}] sheetId={t['sheet_id']:<14} "
                  f"rows={t['rows']:<6} cols={t['cols']:<4} {t['title']}")
        return

    payload = fetch_tab_grid(sheets_service, spreadsheet_id, args.tab)
    summary = summarize_tab(payload, focus_col_letter=args.focus_col)

    if args.out:
        out_path = Path(args.out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({"raw": payload, "summary": summary}, indent=2, default=str))
        md_path = out_path.with_suffix(".md")
        md_path.write_text(render_markdown(summary))
        print(f"wrote {out_path}")
        print(f"wrote {md_path}")
    else:
        print(render_markdown(summary))


if __name__ == "__main__":
    main()
