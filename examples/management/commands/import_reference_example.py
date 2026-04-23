import csv
import os

from importer.base import BaseImportCommand

from examples.models import ExampleBlock, ExampleCrop


class Command(BaseImportCommand):
    help = "Example reference importer using migration_workbench chassis."

    def _run_import_pipeline(self):
        self.tier("TIER 1: Example Reference", self._import_reference)

    def _import_reference(self):
        self._import_blocks()
        self._import_crops()

    def _import_blocks(self):
        path = os.path.join(self.data_dir, "reference", "blocks.csv")
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for i, row in enumerate(reader, 1):
                name = (row.get("Block") or "").strip()
                if not name:
                    continue
                defaults = {
                    "block_type": (row.get("Block Type") or "field").strip().lower().replace(" ", "_"),
                    "num_beds": self._int(row.get("# of Beds"), 0),
                    "bed_width_feet": self._dec(row.get("Bed Width (feet)"), "0"),
                    "bedfeet_per_bed": self._int(row.get("Bedfeet per Bed"), 0),
                }
                if self.write_disabled:
                    self.stats["ExampleBlock"]["processed"] += 1
                    continue
                _, created = ExampleBlock.objects.update_or_create(name=name, defaults=defaults)
                key = "created" if created else "updated"
                self.stats["ExampleBlock"][key] += 1

    def _import_crops(self):
        path = os.path.join(self.data_dir, "reference", "crop_info.csv")
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for i, row in enumerate(reader, 1):
                name = (row.get("Crop") or "").strip()
                if not name:
                    self.record_missing_required("ExampleCrop", i, "Crop", "Crop")
                    self.stats["ExampleCrop"]["errors"] += 1
                    continue
                defaults = {"crop_type": (row.get("Type") or "").strip()}
                if self.write_disabled:
                    self.stats["ExampleCrop"]["processed"] += 1
                    continue
                _, created = ExampleCrop.objects.update_or_create(name=name, defaults=defaults)
                key = "created" if created else "updated"
                self.stats["ExampleCrop"][key] += 1
