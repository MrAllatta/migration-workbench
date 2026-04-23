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
