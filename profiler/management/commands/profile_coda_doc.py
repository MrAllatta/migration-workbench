"""Enumerate tables and views in a Coda doc (and optionally column metadata)."""

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

from profiler.tools.page_profiler import profile_page_composition


def summarize_table_meta(
    table: dict[str, Any], columns: list[dict[str, Any]] | None
) -> dict[str, Any]:
    """Produce a summary dict for a Coda table from its metadata and column list."""
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
                "formula_preview": (
                    (formula_text(c)[:200] + "…")
                    if len(formula_text(c)) > 200
                    else formula_text(c)
                ),
            }
            for c in columns
        ]
    return entry


def render_doc_tree(
    doc_meta: dict[str, Any], tables_payload: list[dict[str, Any]]
) -> str:
    """Render a Coda document's tables and pages as a Markdown tree string."""
    name = doc_meta.get("name") or doc_meta.get("id", "")
    lines = [f"[doc] {name}  (id={doc_meta.get('id')})"]
    for item in tables_payload:
        tname = item.get("name") or item.get("id")
        ttype = item.get("type", "table")
        lines.append(
            f"  [{ttype}]  {tname!r}  (id={item.get('id')})  rows={item.get('rowCount')}  cols={item.get('columnCount')}"
        )
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


def _render_page_tree(pages: list[dict[str, Any]]) -> str:
    """Render page composition as a Markdown tree string.

    Shows the page hierarchy and which tables are embedded on each page.
    """
    lines = ["", "## Page composition", ""]
    for page in pages:
        pname = page.get("name") or page.get("id")
        parent = page.get("parent_page")
        prefix = f"  (under {parent})" if parent else ""
        lines.append(f"[page] {pname!r}{prefix}  (id={page.get('id')})")
        if not page.get("has_content"):
            err = page.get("export_error", "no content")
            lines.append(f"    - (skipped: {err})")
            continue
        et_count = page.get("embedded_table_count", 0)
        if et_count == 0:
            lines.append("    - (no embedded tables)")
            continue
        for et in page.get("tables", []):
            section = et.get("section") or "(no section)"
            match = et.get("matched_table_name")
            match_str = f"  →  {match}" if match else ""
            cols = ", ".join(et.get("headers", [])[:6])
            more = "…" if len(et.get("headers", [])) > 6 else ""
            lines.append(
                f"    - section={section!r}  cols=[{cols}{more}]  rows~{et.get('row_count_preview', 0)}{match_str}"
            )
    return "\n".join(lines) + "\n"


class Command(BaseCommand):
    """Enumerate tables and views in a Coda doc (and optionally column metadata)."""

    help = "Enumerate tables and views in a Coda doc (and optionally column metadata)"

    def add_arguments(self, parser):
        """Add command-line arguments for profile_coda_doc."""
        parser.add_argument(
            "--doc", "--doc-url", dest="doc", help="Coda doc URL or raw doc id"
        )
        parser.add_argument(
            "--no-columns",
            action="store_true",
            help="Skip per-table column enumeration",
        )
        parser.add_argument(
            "--pages",
            action="store_true",
            help="Profile page composition (which tables are on which pages)",
        )
        parser.add_argument(
            "--out", default=None, help="Output JSON path (.md sibling is also written)"
        )
        parser.add_argument(
            "--smoke", action="store_true", help="Run without network calls"
        )

    def handle(self, *args, **options):
        """Execute the Coda doc profiling pipeline. Connects to the Coda API, enumerates tables and pages, and writes a Markdown tree + JSON artifact."""
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

        # Optionally profile page composition
        page_composition = None
        if options.get("pages"):
            self.stdout.write("Profiling page composition…")
            known_tables = {
                (t.get("name") or ""): [
                    c.get("name", "") for c in (t.get("columns") or [])
                ]
                for t in tables_payload
                if t.get("columns")
            }
            page_composition = profile_page_composition(
                session, doc_id, known_tables=known_tables
            )
            self.stdout.write(f"  profiled {len(page_composition)} pages")

        root = {
            "id": doc_meta.get("id"),
            "name": doc_meta.get("name"),
            "href": doc_meta.get("href"),
            "docSize": doc_meta.get("docSize"),
            "tables": tables_payload,
            "page_composition": page_composition,
        }

        rendered = render_doc_tree(doc_meta, tables_payload)
        if page_composition:
            rendered += _render_page_tree(page_composition)
        out = options.get("out")
        if out:
            out_path = Path(out).resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps(root, indent=2, default=str), encoding="utf-8"
            )
            md_path = out_path.with_suffix(".md")
            md_path.write_text(rendered, encoding="utf-8")
            self.stdout.write(f"wrote {out_path}")
            self.stdout.write(f"wrote {md_path}")
        self.stdout.write(rendered, ending="")
