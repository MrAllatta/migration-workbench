from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from connectors.coda_source import (
    build_coda_session,
    column_has_formula,
    formula_text,
    get_doc,
    list_columns,
    list_rows,
    list_tables,
    resolve_doc_id,
    rows_to_grid,
)


def _resolve_table_id(tables: list[dict[str, Any]], table_arg: str) -> tuple[str, str]:
    """Return (table_id, display_name) from id or name."""
    for t in tables:
        if t.get("id") == table_arg or t.get("name") == table_arg:
            return str(t["id"]), str(t.get("name") or t["id"])
    raise ValueError(f"No table or view matching {table_arg!r}")


def summarize_coda_table(
    doc_name: str,
    table_id: str,
    table_name: str,
    columns: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    grid: list[list[str]],
    *,
    focus_col: str | None,
) -> dict[str, Any]:
    formula_cols = [c for c in columns if column_has_formula(c)]
    col_summaries = []
    for c in columns:
        fmt = c.get("format") or {}
        col_summaries.append(
            {
                "id": c.get("id"),
                "name": c.get("name"),
                "format_type": fmt.get("type"),
                "has_formula": column_has_formula(c),
                "formula_text": formula_text(c),
                "default_value": c.get("defaultValue"),
            }
        )

    focus = None
    if focus_col and grid and len(grid) > 0:
        header = grid[0]
        matches = [i for i, h in enumerate(header) if str(h).strip() == focus_col.strip()]
        if matches:
            ci = matches[0]
            col_cells: list[dict[str, Any]] = []
            for ri, row in enumerate(grid[1:], start=2):
                val = row[ci] if ci < len(row) else ""
                col_cells.append({"row": ri, "value": val})
            focus = {
                "column": focus_col,
                "count": len(col_cells),
                "first_20": col_cells[:20],
                "unique_value_sample": [v for v, _ in Counter(c["value"] for c in col_cells).most_common(15)],
            }

    return {
        "doc_name": doc_name,
        "table_id": table_id,
        "table_name": table_name,
        "row_count_api": len(rows),
        "data_row_count": max(len(grid) - 1, 0),
        "column_count": len(columns),
        "columns": col_summaries,
        "formula_column_count": len(formula_cols),
        "formula_columns": [{"name": c.get("name"), "formula_text": formula_text(c)} for c in formula_cols],
        "grid_preview_rows": min(25, len(grid)),
        "grid_preview": grid[: 1 + min(25, max(len(grid) - 1, 0))],
        "focus_column": focus,
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        f"# {summary['doc_name']} / {summary['table_name']}",
        "",
        f"Rows (grid): {summary['data_row_count']}  |  columns: {summary['column_count']}  |  formula columns: {summary['formula_column_count']}",
        "",
        "## Formula columns",
    ]
    for fc in summary.get("formula_columns", [])[:40]:
        ft = fc.get("formula_text") or ""
        preview = (ft[:120] + "…") if len(ft) > 120 else ft
        lines.append(f"- **{fc.get('name')}**: `{preview}`")
    if len(summary.get("formula_columns", [])) > 40:
        lines.append(f"- … {len(summary['formula_columns']) - 40} more")
    lines.extend(["", "## Grid preview (first rows)"])
    for row in summary.get("grid_preview", [])[:12]:
        lines.append("- " + ", ".join(str(x)[:40] for x in row))
    return "\n".join(lines) + "\n"


class Command(BaseCommand):
    help = "Profile one Coda table or view, or list tables in a doc"

    def add_arguments(self, parser):
        parser.add_argument("--doc", "--doc-url", dest="doc", help="Coda doc URL or raw doc id")
        parser.add_argument("--table", default=None, help="Table or view id or name")
        parser.add_argument(
            "--focus-col",
            default=None,
            help="Column name (header) to summarize (Coda uses names, not letters)",
        )
        parser.add_argument("--out", default=None, help="Output JSON path; .md summary is written next to it")
        parser.add_argument(
            "--max-rows",
            type=int,
            default=500,
            help="Maximum rows to fetch for profiling (default 500)",
        )
        parser.add_argument("--smoke", action="store_true", help="Run without network calls")

    def handle(self, *args, **options):
        if options["smoke"]:
            self.stdout.write(self.style.SUCCESS("profile_coda_table smoke ok"))
            return

        doc_value = options.get("doc")
        if not doc_value:
            raise CommandError("--doc is required unless --smoke is used")
        session = build_coda_session()
        doc_id = resolve_doc_id(session, doc_value)
        if not doc_id:
            raise CommandError(f"Could not parse Coda doc id from {doc_value!r}")
        tables = list_tables(session, doc_id)

        if not options.get("table"):
            for t in sorted(tables, key=lambda x: (x.get("name") or "")):
                self.stdout.write(
                    f"type={t.get('type', '?'):<6} id={t.get('id')!s:<18} rows={str(t.get('rowCount')):<6} {t.get('name')!r}"
                )
            return

        table_id, table_name = _resolve_table_id(tables, options["table"])
        columns = list_columns(session, doc_id, table_id)
        max_rows = options["max_rows"]
        rows = list_rows(session, doc_id, table_id, max_rows=max_rows)
        grid = rows_to_grid(columns, rows)
        doc_name = doc_id
        try:
            doc_name = get_doc(session, doc_id).get("name") or doc_id
        except Exception:  # noqa: BLE001
            pass

        summary = summarize_coda_table(
            doc_name,
            table_id,
            table_name,
            columns,
            rows,
            grid,
            focus_col=options.get("focus_col"),
        )
        raw_payload = {"summary": summary, "columns_raw": columns, "rows_sample": rows[:50]}

        out = options.get("out")
        if out:
            out_path = Path(out).resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(raw_payload, indent=2, default=str), encoding="utf-8")
            md_path = out_path.with_suffix(".md")
            md_path.write_text(render_markdown(summary), encoding="utf-8")
            self.stdout.write(f"wrote {out_path}")
            self.stdout.write(f"wrote {md_path}")
            return
        self.stdout.write(render_markdown(summary), ending="")
