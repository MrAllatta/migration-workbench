# Bundle Contract

The profiler emits a normalized bundle directory:

- `manifest.json`
- `reference/*.csv`
- `year_YYYY/*.csv` (optional per importer)

## Header Detection

- Scan first `max_scan_rows` rows (default `200`)
- Use first row containing all `required_headers`
- Fall back to `anchor_token` or explicit `header_row_index`
- Header normalization: trim, collapse spaces, casefold, alias mapping

## Tab Config Fields

- `required_headers`
- `aliases`
- `output_headers`
- `column_map`
- `default_values`
- `row_transforms`
- `source_regions`
- `stop_on_blank_in`
- `grid_unpivot`
- `append_without_header`