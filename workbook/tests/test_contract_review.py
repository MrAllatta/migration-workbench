"""Tests for the contract design-review checklist."""
import pytest
from workbook.codegen.contract import review_contract


class TestReviewContract:
    """Checks that review_contract catches known pitfalls."""

    def test_fk_lookup_references_nonexistent_model(self):
        """Warn when fk_lookup.model targets a model not in the contract."""
        contract = {
            "version": "1.3",
            "tables": [
                {
                    "suggested_model_name": "inventory",
                    "columns": [
                        {
                            "source_column": "Crop",
                            "suggested_field_name": "crop",
                            "django_field_class": "models.ForeignKey",
                            "django_field_kwargs": {"to": "Crop"},
                        },
                    ],
                    "str_template": "{self.crop}",
                    "import_config": {
                        "fk_lookup": {
                            "crop": {"model": "NonExistentModel", "on": "name"},
                        },
                    },
                },
            ],
        }
        issues = review_contract(contract)
        assert any(
            "NonExistentModel" in i["message"] and "fk_lookup" in i["message"]
            for i in issues
        )

    def test_admin_inlines_target_nonexistent_model(self):
        """Warn when admin.inlines references a model not in the contract."""
        contract = {
            "version": "1.3",
            "tables": [
                {
                    "suggested_model_name": "planting",
                    "columns": [
                        {
                            "source_column": "Name",
                            "suggested_field_name": "name",
                            "django_field_class": "models.CharField",
                            "django_field_kwargs": {"max_length": 100},
                        },
                    ],
                    "str_template": "{self.name}",
                    "admin": {
                        "inlines": ["MissingInlineModel"],
                    },
                },
            ],
        }
        issues = review_contract(contract)
        assert any(
            "MissingInlineModel" in i["message"] and "inlines" in i["message"]
            for i in issues
        )

    def test_computed_field_naming_convention(self):
        """Warn when computed_fields use non-snake_case names."""
        contract = {
            "version": "1.3",
            "tables": [
                {
                    "suggested_model_name": "crop",
                    "columns": [
                        {
                            "source_column": "Name",
                            "suggested_field_name": "name",
                            "django_field_class": "models.CharField",
                            "django_field_kwargs": {"max_length": 100},
                        },
                    ],
                    "str_template": "{self.name}",
                    "computed_fields": {
                        "signedQuantity": {
                            "return_type": "int",
                            "expression": "self.quantity * -1",
                        },
                    },
                },
            ],
        }
        issues = review_contract(contract)
        assert any(
            "signedQuantity" in i["message"] and "snake_case" in i["message"]
            for i in issues
        )

    def test_clean_contract_no_issues(self):
        """A well-formed minimal contract produces no review issues."""
        contract = {
            "version": "1.3",
            "tables": [
                {
                    "suggested_model_name": "crop",
                    "columns": [
                        {
                            "source_column": "Name",
                            "suggested_field_name": "name",
                            "django_field_class": "models.CharField",
                            "django_field_kwargs": {"max_length": 100},
                        },
                    ],
                    "str_template": "{self.name}",
                },
            ],
        }
        issues = review_contract(contract)
        assert len(issues) == 0
