import json
from pathlib import Path

import yaml
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Generate source_config.json from a contract and workbook index."

    def add_arguments(self, parser):
        parser.add_argument("--contract", required=True, help="Path to contract YAML")
        parser.add_argument(
            "--index", required=True, help="Path to workbook index JSON"
        )
        parser.add_argument(
            "--out", required=True, help="Output path for source_config.json"
        )
        parser.add_argument(
            "--provider",
            default="google_sheets",
            help="Provider (default: google_sheets)",
        )

    def handle(self, *args, **options):
        contract_path = Path(options["contract"])
        index_path = Path(options["index"])
        out_path = Path(options["out"])
        provider = options["provider"]

        if not contract_path.exists():
            raise CommandError(f"Contract not found: {contract_path}")
        if not index_path.exists():
            raise CommandError(f"Index not found: {index_path}")

        with open(contract_path) as f:
            contract = yaml.safe_load(f)
        with open(index_path) as f:
            index_data = json.load(f)

        tabs = []
        for table in contract.get("tables", []):
            import_cfg = table.get("import_config") or {}
            tab = {
                "worksheet_title": table.get("bundle_worksheet_title")
                or table.get("suggested_model_name", ""),
                "output_path": import_cfg.get("bundle_path") or "",
                "required_headers": import_cfg.get("required_headers") or [],
            }
            if import_cfg.get("column_map"):
                tab["column_map"] = import_cfg["column_map"]
            if import_cfg.get("defaults"):
                tab["default_values"] = import_cfg["defaults"]
            if import_cfg.get("unique_on"):
                tab["unique_on"] = import_cfg["unique_on"]
            tabs.append(tab)

        years = {}
        for wb in index_data.get("workbooks", []):
            year = wb.get("year")
            if year:
                years[str(year)] = {
                    "spreadsheet_id": wb.get("spreadsheet_id", ""),
                    "source_bundle_year": year,
                }

        config = {
            "provider": provider,
            "source_id": contract.get("source_id") or "",
            "tabs": tabs,
        }
        if years:
            config["years"] = years

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(config, f, indent=2)

        self.stdout.write(self.style.SUCCESS(f"Wrote {out_path}"))
