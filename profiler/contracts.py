# source_config supports:
# - worksheet_title_by_year: {"2023": "Products", "2024": "Products 302 + 602"}
#   Maps year strings to year-specific worksheet titles. Falls back to
#   worksheet_title if the year is not found.
# - years: {"2023": {"spreadsheet_id": "...", "source_bundle_year": 2023}, ...}
#   Top-level mapping that replicates tab entries per year.

LIVE_SOURCE_NORMALIZER_CONTRACT = {
    "schema_version": "bundle-draft-1",
    "header_detection": {
        "strategy": "required_header_set_scan",
        "max_scan_rows": 200,
        "normalization": ["trim", "collapse_spaces", "casefold", "alias_lookup"],
        "fallbacks": ["anchor_token", "header_row_index"],
    },
    "output_layout": {
        "reference": "reference/*.csv",
        "yearly": "year_YYYY/*.csv",
        "manifest": "manifest.json",
    },
}
