from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from connectors.google_sheets import (
    DRIVE_READONLY_SCOPE,
    SHEETS_READONLY_SCOPE,
    build_google_service,
    extract_spreadsheet_id,
)


def _col_letter(idx0: int) -> str:
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
    fields = (
        "properties(title),"
        "sheets(properties(sheetId,title,gridProperties),"
        "data(startRow,startColumn,rowData(values("
        "formattedValue,userEnteredValue,effectiveValue,note,dataValidation"
        "))))"
    )
    range_ = f"'{tab_title.replace(chr(39), chr(39) * 2)}'"
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


def formula_skeleton(formula: str) -> str:
    text = formula
    text = re.sub(r"'([^']*)'!", lambda m: f"'{m.group(1)}'!", text)
    text = re.sub(r"\$?[A-Z]+\$?\d+(?::\$?[A-Z]+\$?\d+)?", "<RANGE>", text)
    text = re.sub(r"\$?[A-Z]+:\$?[A-Z]+", "<COLRANGE>", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\b", "<N>", text)
    return text


SHEET_REF_RE = re.compile(r"'([^']+)'!|\b([A-Za-z_][A-Za-z0-9_]*)!")
IMPORTRANGE_RE = re.compile(r'IMPORTRANGE\s*\(\s*"([^"]+)"\s*,\s*"([^"]+)"', re.IGNORECASE)
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
    cells: list[dict] = []
    for block in data_blocks:
        start_row = block.get("startRow", 0)
        start_col = block.get("startColumn", 0)
        for r_off, row in enumerate(block.get("rowData", [])):
            for c_off, cell in enumerate(row.get("values", []) or []):
                kind, text = _user_entered_repr(cell.get("userEnteredValue"))
                cells.append(
                    {
                        "row": start_row + r_off + 1,
                        "col": start_col + c_off,
                        "col_letter": _col_letter(start_col + c_off),
                        "kind": kind,
                        "user_entered": text,
                        "formatted": cell.get("formattedValue", ""),
                        "note": cell.get("note"),
                        "data_validation": cell.get("dataValidation"),
                    }
                )

    formulas = [c for c in cells if c["kind"] == "formula"]
    skeleton_counts: Counter = Counter()
    func_counts: Counter = Counter()
    sheet_ref_counts: Counter = Counter()
    import_ranges: list[dict] = []
    for c in formulas:
        sk = formula_skeleton(c["user_entered"])
        skeleton_counts[sk] += 1
        info = extract_references(c["user_entered"])
        for f_name in info["functions"]:
            func_counts[f_name] += 1
        for sheet_ref in info["sheet_refs"]:
            sheet_ref_counts[sheet_ref] += 1
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
        dv_rules.append({"example_cell": f"{c['col_letter']}{c['row']}", "rule": dv})

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
    lines = [f"# {summary['workbook_title']} / {summary['tab_title']}", ""]
    g = summary["grid"]
    lines.append(
        f"Grid: {g['rows']} rows x {g['cols']} cols  |  non-empty cells: {summary['cell_count']}  |  formula cells: {summary['formula_cell_count']}"
    )
    lines.extend(["", "## Functions used"])
    lines.append(", ".join(f"{fn}({n})" for fn, n in summary["functions_used"]))
    lines.extend(["", "## Top formula skeletons"])
    for sk, n in summary["unique_formula_skeletons"][:30]:
        lines.append(f"- ({n}x) `{sk}`")
    return "\n".join(lines) + "\n"


class Command(BaseCommand):
    help = "Profile one workbook tab, or list workbook tabs"

    def add_arguments(self, parser):
        parser.add_argument("--spreadsheet-id", help="Spreadsheet id or URL")
        parser.add_argument("--tab", help="Worksheet tab title. If omitted, list tabs and exit")
        parser.add_argument("--focus-col", default=None, help="Column letter to trace (e.g. B)")
        parser.add_argument("--out", default=None, help="Output JSON path; .md summary is written next to it")
        parser.add_argument("--smoke", action="store_true", help="Run without network calls")

    def handle(self, *args, **options):
        if options["smoke"]:
            self.stdout.write(self.style.SUCCESS("profile_tab smoke ok"))
            return

        spreadsheet_value = options.get("spreadsheet_id")
        if not spreadsheet_value:
            raise CommandError("--spreadsheet-id is required unless --smoke is used")
        spreadsheet_id = extract_spreadsheet_id(spreadsheet_value)
        scopes = [SHEETS_READONLY_SCOPE, DRIVE_READONLY_SCOPE]
        sheets_service = build_google_service("sheets", "v4", scopes)

        if not options.get("tab"):
            tabs = list_tabs(sheets_service, spreadsheet_id)
            for t in tabs:
                self.stdout.write(
                    f"[{t['index']:>2}] sheetId={t['sheet_id']:<14} rows={t['rows']:<6} cols={t['cols']:<4} {t['title']}"
                )
            return

        payload = fetch_tab_grid(sheets_service, spreadsheet_id, options["tab"])
        summary = summarize_tab(payload, focus_col_letter=options.get("focus_col"))
        out = options.get("out")
        if out:
            out_path = Path(out).resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps({"raw": payload, "summary": summary}, indent=2, default=str), encoding="utf-8")
            md_path = out_path.with_suffix(".md")
            md_path.write_text(render_markdown(summary), encoding="utf-8")
            self.stdout.write(f"wrote {out_path}")
            self.stdout.write(f"wrote {md_path}")
            return
        self.stdout.write(render_markdown(summary), ending="")
