from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from connectors.google_sheets import (
    DRIVE_READONLY_SCOPE,
    SHEETS_READONLY_SCOPE,
    SPREADSHEET_MIME_TYPE,
    build_google_service,
    extract_drive_folder_id,
)

FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


def list_children(drive_service, folder_id: str) -> list[dict]:
    items: list[dict] = []
    page_token: str | None = None
    query = f"'{folder_id}' in parents and trashed=false"
    while True:
        response = (
            drive_service.files()
            .list(
                q=query,
                fields="nextPageToken, files(id, name, mimeType, modifiedTime, size)",
                orderBy="folder,name",
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        items.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return items


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
            "index": s["properties"].get("index"),
            "sheet_id": s["properties"].get("sheetId"),
            "title": s["properties"].get("title"),
            "rows": s["properties"].get("gridProperties", {}).get("rowCount"),
            "cols": s["properties"].get("gridProperties", {}).get("columnCount"),
        }
        for s in response.get("sheets", [])
    ]


def walk_folder(
    drive_service,
    sheets_service,
    folder_id: str,
    *,
    include_tabs: bool,
    max_depth: int | None,
    _depth: int = 0,
) -> dict[str, Any]:
    children = list_children(drive_service, folder_id)
    sub_folders: list[dict] = []
    spreadsheets: list[dict] = []
    other: list[dict] = []
    for child in children:
        mime = child.get("mimeType")
        if mime == FOLDER_MIME_TYPE:
            sub_folders.append(child)
        elif mime == SPREADSHEET_MIME_TYPE:
            spreadsheets.append(child)
        else:
            other.append(child)

    sheet_entries: list[dict] = []
    for item in spreadsheets:
        entry = {
            "id": item["id"],
            "name": item.get("name"),
            "modifiedTime": item.get("modifiedTime"),
            "tabs": None,
            "error": None,
        }
        if include_tabs:
            try:
                entry["tabs"] = list_tabs(sheets_service, item["id"])
            except Exception as exc:  # noqa: BLE001
                entry["error"] = f"{type(exc).__name__}: {exc}"
        sheet_entries.append(entry)

    folder_entries: list[dict] = []
    for sub in sub_folders:
        if max_depth is not None and _depth + 1 >= max_depth:
            folder_entries.append(
                {
                    "id": sub["id"],
                    "name": sub.get("name"),
                    "modifiedTime": sub.get("modifiedTime"),
                    "truncated": True,
                }
            )
            continue
        folder_entries.append(
            walk_folder(
                drive_service,
                sheets_service,
                sub["id"],
                include_tabs=include_tabs,
                max_depth=max_depth,
                _depth=_depth + 1,
            )
            | {
                "id": sub["id"],
                "name": sub.get("name"),
                "modifiedTime": sub.get("modifiedTime"),
            }
        )

    return {
        "folders": folder_entries,
        "spreadsheets": sheet_entries,
        "other_files": other,
    }


def render_tree(node: dict, *, name: str, prefix: str = "") -> list[str]:
    lines: list[str] = [f"{prefix}[folder] {name}"]
    child_prefix = prefix + "  "
    for sub in node.get("folders", []):
        if sub.get("truncated"):
            lines.append(f"{child_prefix}[folder] {sub.get('name')}  (truncated, id={sub.get('id')})")
            continue
        lines.extend(render_tree(sub, name=sub.get("name") or sub.get("id"), prefix=child_prefix))
    for sheet in node.get("spreadsheets", []):
        header = f"{child_prefix}[sheet]  {sheet.get('name')}  (id={sheet['id']})"
        lines.append(header)
        tabs = sheet.get("tabs")
        if sheet.get("error"):
            lines.append(f"{child_prefix}  !! tabs unavailable: {sheet['error']}")
        elif tabs is not None:
            for tab in tabs:
                lines.append(
                    f"{child_prefix}  - tab[{tab['index']:>2}] {tab['title']!r}  rows={tab['rows']}  cols={tab['cols']}"
                )
    for other in node.get("other_files", []):
        lines.append(f"{child_prefix}[other]  {other.get('name')}  ({other.get('mimeType')})")
    return lines


class Command(BaseCommand):
    help = "Enumerate a Drive folder tree and list spreadsheet tabs"

    def add_arguments(self, parser):
        parser.add_argument("--folder", help="Drive folder id or URL")
        parser.add_argument("--no-tabs", action="store_true", help="Skip spreadsheet tab enumeration")
        parser.add_argument("--max-depth", type=int, default=None, help="Maximum folder recursion depth")
        parser.add_argument("--out", default=None, help="Output JSON path (.md sibling is also written)")
        parser.add_argument("--smoke", action="store_true", help="Run without network calls")

    def handle(self, *args, **options):
        if options["smoke"]:
            self.stdout.write(self.style.SUCCESS("profile_drive_folder smoke ok"))
            return

        folder = options.get("folder")
        if not folder:
            raise CommandError("--folder is required unless --smoke is used")
        folder_id = extract_drive_folder_id(folder)
        scopes = [SHEETS_READONLY_SCOPE, DRIVE_READONLY_SCOPE]
        drive_service = build_google_service("drive", "v3", scopes)
        sheets_service = build_google_service("sheets", "v4", scopes)

        folder_meta = (
            drive_service.files()
            .get(
                fileId=folder_id,
                fields="id,name,mimeType,modifiedTime",
                supportsAllDrives=True,
            )
            .execute()
        )
        if folder_meta.get("mimeType") != FOLDER_MIME_TYPE:
            raise CommandError(f"{folder_id} is not a Drive folder (mimeType={folder_meta.get('mimeType')})")

        tree = walk_folder(
            drive_service,
            sheets_service,
            folder_id,
            include_tabs=not options["no_tabs"],
            max_depth=options["max_depth"],
        )
        tree_root = {
            "id": folder_meta["id"],
            "name": folder_meta.get("name"),
            "modifiedTime": folder_meta.get("modifiedTime"),
            **tree,
        }

        rendered = "\n".join(render_tree(tree_root, name=tree_root["name"] or folder_id)) + "\n"
        out = options.get("out")
        if out:
            out_path = Path(out).resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(tree_root, indent=2, default=str), encoding="utf-8")
            md_path = out_path.with_suffix(".md")
            md_path.write_text(rendered, encoding="utf-8")
            self.stdout.write(f"wrote {out_path}")
            self.stdout.write(f"wrote {md_path}")
        self.stdout.write(rendered, ending="")
