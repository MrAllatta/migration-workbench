# Pipeline Narrative

`migration-workbench` is organized as a staged migration pipeline:

1. **Wild intake**
   - Input: workbook/doc identifiers and source config.
   - Output: connector-level source access and preflight metadata.
2. **Profile**
   - Commands under `profiler` collect tab/table structure and formula signals.
   - Output artifacts: JSON/Markdown snapshots under `build/` or product-owned `data/profile_snapshots/`.
3. **Model**
   - `workbook.scaffold_workbook_schema` turns profile artifacts + tab config into schema-contract YAML.
   - Optional output: review-only `models.py` stub.
4. **Harden**
   - `importer` command chassis executes validate/apply loops against normalized bundles.
   - Output artifacts: summary JSON and deterministic failure records.
5. **Deploy**
   - `wb manifest lint` validates `deploy/spaces.yml`.
   - `wb deploy <space> --env <env> --dry-run` resolves a release plan and records release metadata.
   - Output artifacts: database release records plus append-only JSONL release events.
