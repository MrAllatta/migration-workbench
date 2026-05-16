import copy
import csv
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from connectors.router import build_provider_adapter
from connectors.spreadsheet import normalize_rows
from profiler.contracts import LIVE_SOURCE_NORMALIZER_CONTRACT


STRUCTURE_SCHEMA_VERSION = "structure-draft-1"


def resolve_tab_title_for_year(tab: dict, year: int | None) -> str:
    title_by_year = tab.get("worksheet_title_by_year") or {}
    if year is not None:
        year_key = str(year)
        if year_key in title_by_year:
            return title_by_year[year_key]
    return tab.get("worksheet_title", "")


def expand_years_config(config: dict) -> dict:
    years = config.get("years")
    if not years:
        return config

    result = copy.deepcopy(config)
    result.pop("years", None)
    expanded_tabs = []

    for year_key, year_info in years.items():
        year = int(year_key) if isinstance(year_key, str) else year_key
        spreadsheet_id = year_info.get("spreadsheet_id", config.get("doc_id", ""))
        source_bundle_year = year_info.get("source_bundle_year", year)

        for tab in config.get("tabs", []):
            tab_copy = copy.deepcopy(tab)
            tab_copy["spreadsheet_id"] = spreadsheet_id
            tab_copy["source_bundle_year"] = source_bundle_year

            title = resolve_tab_title_for_year(tab_copy, year)
            tab_copy["worksheet_title"] = title
            tab_copy.pop("worksheet_title_by_year", None)

            original_path = tab_copy.get("output_path", "")
            base = original_path.rsplit(".", 1)[0] if "." in original_path else original_path
            ext = original_path.rsplit(".", 1)[1] if "." in original_path else "csv"
            tab_copy["output_path"] = f"{year}/{base}.{ext}"

            defaults = tab_copy.setdefault("default_values", {})
            defaults["source_bundle_year"] = source_bundle_year

            expanded_tabs.append(tab_copy)

    result["tabs"] = expanded_tabs
    return result


class Command(BaseCommand):
    help = "Fetch provider tabs and normalize them into a bundle"

    def add_arguments(self, parser):
        parser.add_argument("--config", required=True, help="JSON config describing live source tabs")
        parser.add_argument("--output-dir", required=True, help="Directory for the normalized bundle")
        parser.add_argument(
            "--include-structure",
            action="store_true",
            help=(
                "Also emit structure.json with per-tab UI metadata (headers, "
                "formula columns, validation types, frozen panes). Adapters that "
                "do not implement structure capture are silently skipped."
            ),
        )

    def handle(self, *args, **options):
        config_path = Path(options["config"]).resolve()
        output_dir = Path(options["output_dir"]).resolve()
        if not config_path.exists():
            raise CommandError(f"Config not found: {config_path}")

        config = json.loads(config_path.read_text(encoding="utf-8"))
        config = expand_years_config(config)
        tabs = config.get("tabs", [])
        if not tabs:
            raise CommandError("Config must include at least one tab entry")

        provider_name = (config.get("provider") or "google_sheets").strip().casefold()
        provider = build_provider_adapter(config)

        output_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema_version": LIVE_SOURCE_NORMALIZER_CONTRACT["schema_version"],
            "source_id": config.get("source_id", f"{provider_name}-bundle"),
            "connector_version": "bundle-connector-1",
            "provider": provider_name,
            "tabs": [],
        }

        include_structure = bool(options.get("include_structure"))
        structure_tabs: list[dict] = []

        default_scan_rows = LIVE_SOURCE_NORMALIZER_CONTRACT["header_detection"]["max_scan_rows"]

        for tab in tabs:
            worksheet_title = resolve_tab_title_for_year(tab, tab.get("source_bundle_year"))
            if not worksheet_title:
                raise CommandError("Each tab entry must include worksheet_title")

            pulled = provider.fetch_tab_rows(tab)
            rows = pulled["rows"]
            if not rows:
                raise CommandError(
                    f"Worksheet '{worksheet_title}' returned no rows from provider '{provider_name}'"
                )

            if include_structure:
                # Reuse the resolved spreadsheet id so the adapter avoids a
                # second name->id lookup against Drive.
                tab_with_resolved = dict(tab)
                if pulled.get("spreadsheet_id"):
                    tab_with_resolved.setdefault("spreadsheet_id", pulled["spreadsheet_id"])
                structure_entry = provider.fetch_tab_structure(tab_with_resolved)
                if structure_entry is not None:
                    structure_tabs.append(structure_entry)

            normalized = normalize_rows(
                rows,
                required_headers=tab["required_headers"],
                aliases=tab.get("aliases"),
                max_scan_rows=tab.get("max_scan_rows", default_scan_rows),
                anchor_token=tab.get("anchor_token"),
                header_row_index=tab.get("header_row_index"),
                output_headers=tab.get("output_headers"),
                column_map=tab.get("column_map"),
                default_values=tab.get("default_values"),
                row_transforms=tab.get("row_transforms"),
                source_regions=tab.get("source_regions"),
                stop_on_blank_in=tab.get("stop_on_blank_in"),
                prefer_anchor_token=tab.get("prefer_anchor_token", False),
                grid_unpivot=tab.get("grid_unpivot"),
            )

            output_path = output_dir / tab["output_path"]
            output_path.parent.mkdir(parents=True, exist_ok=True)
            append_without_header = tab.get("append_without_header", False)
            data_rows = normalized["rows"][1:]
            appended_data_only = append_without_header and output_path.exists()
            if appended_data_only:
                with output_path.open("a", encoding="utf-8", newline="") as handle:
                    writer = csv.writer(handle)
                    writer.writerows(data_rows)
                rows_written = len(data_rows)
            else:
                with output_path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.writer(handle)
                    writer.writerows(normalized["rows"])
                rows_written = max(len(normalized["rows"]) - 1, 0)

            tab_manifest = {
                "source_id": pulled["spreadsheet_id"],
                "source_name": pulled["spreadsheet_name"],
                "worksheet_title": worksheet_title,
                "output_path": tab["output_path"],
                "header_row_index": normalized["header_row_index"],
                "strategy": normalized["strategy"],
                "rows_written": rows_written,
                "modified_time": pulled.get("modified_time"),
            }
            if append_without_header:
                tab_manifest["append_without_header"] = True
            if tab.get("grid_unpivot"):
                tab_manifest["grid_unpivot"] = True
            manifest["tabs"].append(tab_manifest)
            self.stdout.write(
                f"pulled {pulled['spreadsheet_name']}:{worksheet_title} -> {tab['output_path']}"
            )

        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"wrote bundle manifest: {manifest_path}"))

        if include_structure and structure_tabs:
            structure = {
                "schema_version": STRUCTURE_SCHEMA_VERSION,
                "source_id": manifest["source_id"],
                "provider": provider_name,
                "tabs": structure_tabs,
            }
            structure_path = output_dir / "structure.json"
            structure_path.write_text(
                json.dumps(structure, indent=2, sort_keys=True), encoding="utf-8"
            )
            self.stdout.write(self.style.SUCCESS(f"wrote bundle structure: {structure_path}"))
        elif include_structure:
            self.stdout.write(
                "include-structure requested but no adapter returned structural metadata; skipping structure.json"
            )
