# Authoring Importers

Create a Django management command subclassing `importer.base.BaseImportCommand`.

Required:

- Implement `_run_import_pipeline(self)`
- Use `self.tier(name, callback)` for deterministic logging bands

Available chassis helpers:

- `self.record_row_error(...)`
- `self.record_missing_required(...)`
- `self.record_stale_fk(...)`
- `self._resolve_fk_by_text(model, field_name, raw_value, label)`
- `self._int(...)`, `self._dec(...)`, date and split helpers

Modes:

- `--validate-only` / `--preflight`: full import path under rollback transaction
- `--dry-run`: parse-only checks
- apply (default): writes records

Summary artifacts:

- `--summary-json /path/to/file.json`
- schema version: `1.0`
- includes per-model outcomes, row errors, failure signatures, and escalation summary
