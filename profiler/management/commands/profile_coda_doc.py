from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from connectors.coda_source import (
    build_coda_session,
    column_has_formula,
    formula_text,
    get_doc,
    list_columns,
    list_tables,
    resolve_doc_id,
)


def summarize_table_meta(table: dict[str, Any], columns: list[dict[str, Any]] | None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": table.get("id"),
        "name": table.get("name"),
        "type": table.get("type"),
        "parentTable": table.get("parentTable"),
        "rowCount": table.get("rowCount"),
        "columnCount": table.get("columnCount"),
    }
    if columns is not None:
        entry["columnCount"] = len(columns)
        entry["columns"] = [
            {
                "id": c.get("id"),
                "name": c.get("name"),
                "format_type": (c.get("format") or {}).get("type"),
                "has_formula": column_has_formula(c),
                "formula_preview": (formula_text(c)[:200] + "…")
                if len(formula_text(c)) > 200
                else formula_text(c),
            }
            for c in columns
        ]
    return entry


def render_doc_tree(doc_meta: dict[str, Any], tables_payload: list[dict[str, Any]]) -> str:
    name = doc_meta.get("name") or doc_meta.get("id", "")
    lines = [f"[doc] {name}  (id={doc_meta.get('id')})"]
    for item in tables_payload:
        tname = item.get("name") or item.get("id")
        ttype = item.get("type", "table")
        lines.append(f"  [{ttype}]  {tname!r}  (id={item.get('id')})  rows={item.get('rowCount')}  cols={item.get('columnCount')}")
        cols = item.get("columns")
        if cols:
            for c in cols[:40]:
                fn = c.get("formula_preview") or ""
                flag = " formula" if c.get("has_formula") else ""
                lines.append(
                    f"    - col {c.get('name')!r}  type={c.get('format_type')}{flag}"
                    + (f"  `{fn[:60]}`" if fn else "")
                )
            if len(cols) > 40:
                lines.append(f"    … {len(cols) - 40} more columns")
    return "\n".join(lines) + "\n"


class Command(BaseCommand):
    help = "Enumerate tables and views in a Coda doc (and optionally column metadata)"

    def add_arguments(self, parser):
        parser.add_argument("--doc", "--doc-url", dest="doc", help="Coda doc URL or raw doc id")
        parser.add_argument("--no-columns", action="store_true", help="Skip per-table column enumeration")
        parser.add_argument("--out", default=None, help="Output JSON path (.md sibling is also written)")
        parser.add_argument("--smoke", action="store_true", help="Run without network calls")

    def handle(self, *args, **options):
        if options["smoke"]:
            self.stdout.write(self.style.SUCCESS("profile_coda_doc smoke ok"))
            return

        doc_value = options.get("doc")
        if not doc_value:
            raise CommandError("--doc is required unless --smoke is used")
        session = build_coda_session()
        doc_id = resolve_doc_id(session, doc_value)
        if not doc_id:
            raise CommandError(f"Could not parse Coda doc id from {doc_value!r}")

        doc_meta = get_doc(session, doc_id)
        tables = list_tables(session, doc_id)

        tables_payload: list[dict[str, Any]] = []
        for table in tables:
            tid = table.get("id")
            if options["no_columns"] or not tid:
                tables_payload.append(summarize_table_meta(table, None))
                continue
            try:
                cols = list_columns(session, doc_id, tid)
            except Exception as exc:  # noqa: BLE001
                tables_payload.append(
                    summarize_table_meta(table, None)
                    | {"column_list_error": f"{type(exc).__name__}: {exc}"}
                )
                continue
            tables_payload.append(summarize_table_meta(table, cols))

        root = {
            "id": doc_meta.get("id"),
            "name": doc_meta.get("name"),
            "href": doc_meta.get("href"),
            "tables": tables_payload,
        }

        rendered = render_doc_tree(doc_meta, tables_payload)
        out = options.get("out")
        if out:
            out_path = Path(out).resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(root, indent=2, default=str), encoding="utf-8")
            md_path = out_path.with_suffix(".md")
            md_path.write_text(rendered, encoding="utf-8")
            self.stdout.write(f"wrote {out_path}")
            self.stdout.write(f"wrote {md_path}")
        self.stdout.write(rendered, ending="")
