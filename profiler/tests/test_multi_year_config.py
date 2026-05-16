from profiler.management.commands.pull_bundle import resolve_tab_title_for_year, expand_years_config


class TestResolveTabTitleForYear:
    def test_falls_back_to_worksheet_title(self):
        tab = {"worksheet_title": "Products 302 + 602"}
        assert resolve_tab_title_for_year(tab, 2023) == "Products 302 + 602"

    def test_uses_year_specific_title(self):
        tab = {
            "worksheet_title": "Products 302 + 602",
            "worksheet_title_by_year": {"2023": "Products", "2024": "Products 302 + 602"},
        }
        assert resolve_tab_title_for_year(tab, 2023) == "Products"
        assert resolve_tab_title_for_year(tab, 2024) == "Products 302 + 602"

    def test_missing_year_falls_back(self):
        tab = {
            "worksheet_title": "Products 302 + 602",
            "worksheet_title_by_year": {"2024": "Products 302 + 602"},
        }
        assert resolve_tab_title_for_year(tab, 2023) == "Products 302 + 602"

    def test_with_plus_in_title(self):
        tab = {
            "worksheet_title": "Products 302 + 602",
            "worksheet_title_by_year": {"2023": "Products"},
        }
        assert resolve_tab_title_for_year(tab, 2023) == "Products"

    def test_none_year_ignores_mapping(self):
        tab = {
            "worksheet_title": "Products 302 + 602",
            "worksheet_title_by_year": {"2023": "Products"},
        }
        assert resolve_tab_title_for_year(tab, None) == "Products 302 + 602"


class TestExpandYearsConfig:
    def test_no_years_returns_original_config(self):
        config = {"provider": "google_sheets", "source_id": "farm", "tabs": []}
        result = expand_years_config(config)
        assert result == config

    def test_years_creates_per_year_tabs(self):
        config = {
            "provider": "google_sheets",
            "source_id": "farm",
            "years": {
                "2023": {"spreadsheet_id": "1abc", "source_bundle_year": 2023},
                "2024": {"spreadsheet_id": "1def", "source_bundle_year": 2024},
            },
            "tabs": [
                {"worksheet_title": "Products", "output_path": "products.csv", "required_headers": ["Name"]},
            ],
        }
        result = expand_years_config(config)
        assert len(result["tabs"]) == 2
        assert result["tabs"][0]["spreadsheet_id"] == "1abc"
        assert result["tabs"][0].get("source_bundle_year") == 2023
        assert result["tabs"][1]["spreadsheet_id"] == "1def"

    def test_years_with_output_path_subdirs(self):
        config = {
            "provider": "google_sheets",
            "source_id": "farm",
            "years": {
                "2023": {"spreadsheet_id": "1abc", "source_bundle_year": 2023},
            },
            "tabs": [
                {"worksheet_title": "Products", "output_path": "products.csv", "required_headers": ["Name"]},
            ],
        }
        result = expand_years_config(config)
        assert "2023" in result["tabs"][0]["output_path"]

    def test_years_injects_source_bundle_year_default(self):
        config = {
            "provider": "google_sheets",
            "source_id": "farm",
            "years": {
                "2023": {"spreadsheet_id": "1abc", "source_bundle_year": 2023},
            },
            "tabs": [
                {"worksheet_title": "Products", "output_path": "products.csv", "required_headers": ["Name"]},
            ],
        }
        result = expand_years_config(config)
        defaults = result["tabs"][0].get("default_values", {})
        assert defaults.get("source_bundle_year") == 2023