import csv
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from connectors.router import build_provider_adapter
from connectors.spreadsheet import normalize_rows
from profiler.contracts import LIVE_SOURCE_NORMALIZER_CONTRACT


class Command(BaseCommand):
    help = "Fetch provider tabs and normalize them into a bundle"

    def add_arguments(self, parser):
        parser.add_argument("--config", required=True, help="JSON config describing live source tabs")
        parser.add_argument("--output-dir", required=True, help="Directory for the normalized bundle")

    def handle(self, *args, **options):
        config_path = Path(options["config"]).resolve()
        output_dir = Path(options["output_dir"]).resolve()
        if not config_path.exists():
            raise CommandError(f"Config not found: {config_path}")

        config = json.loads(config_path.read_text(encoding="utf-8"))
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

        default_scan_rows = LIVE_SOURCE_NORMALIZER_CONTRACT["header_detection"]["max_scan_rows"]

        for tab in tabs:
            worksheet_title = tab.get("worksheet_title")
            if not worksheet_title:
                raise CommandError("Each tab entry must include worksheet_title")

            pulled = provider.fetch_tab_rows(tab)
            rows = pulled["rows"]
            if not rows:
                raise CommandError(
                    f"Worksheet '{worksheet_title}' returned no rows from provider '{provider_name}'"
                )

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
