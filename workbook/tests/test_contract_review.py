"""Tests for the contract design-review checklist."""

from workbook.codegen.contract import review_contract


class TestReviewContract:
    """Checks that review_contract catches known pitfalls."""

    def test_fk_lookup_references_nonexistent_model(self):
        """Warn when fk_lookup.model targets a model not in the contract."""
        contract = {
            "tables": [
                {
                    "suggested_model_name": "inventory",
                    "model_name": "Inventory",
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
            "tables": [
                {
                    "suggested_model_name": "planting",
                    "model_name": "Planting",
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
            "tables": [
                {
                    "suggested_model_name": "crop",
                    "model_name": "Crop",
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
            "tables": [
                {
                    "suggested_model_name": "crop",
                    "model_name": "Crop",
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

    def test_all_issues_include_rule_id(self):
        """Every issue produced by review_contract must have a rule_id key."""
        contract = {
            "tables": [
                {
                    "suggested_model_name": "planting",
                    "model_name": "Planting",
                    "columns": [
                        {
                            "source_column": "Crop",
                            "suggested_field_name": "crop",
                            "django_field_class": "models.ForeignKey",
                            "django_field_kwargs": {"to": "Crop"},
                        },
                        {
                            "source_column": "Field",
                            "suggested_field_name": "field",
                            "django_field_class": "models.ForeignKey",
                            "django_field_kwargs": {"to": "Field"},
                        },
                    ],
                    "str_template": "{self.crop}",
                },
            ],
        }
        issues = review_contract(contract)
        assert len(issues) > 0, "Expected at least one issue from multi-FK contract"
        assert all("rule_id" in issue for issue in issues), (
            f"Missing rule_id in issues: {issues}"
        )

    def test_suppress_review_warning_multiple_fk_without_unique(self):
        """Allow suppressing specific review warnings per table by rule_id."""
        contract = {
            "tables": [
                {
                    "suggested_model_name": "planting",
                    "model_name": "Planting",
                    "columns": [
                        {
                            "source_column": "Crop",
                            "suggested_field_name": "crop",
                            "django_field_class": "models.ForeignKey",
                            "django_field_kwargs": {"to": "Crop"},
                        },
                        {
                            "source_column": "Field",
                            "suggested_field_name": "field",
                            "django_field_class": "models.ForeignKey",
                            "django_field_kwargs": {"to": "Field"},
                        },
                    ],
                    "str_template": "{self.crop}",
                },
            ],
        }
        issues = review_contract(contract)
        assert any(i.get("rule_id") == "multiple_fk_without_unique" for i in issues)

        suppressed_contract = {
            **contract,
            "tables": [
                {
                    **contract["tables"][0],
                    "suppress_review_warnings": ["multiple_fk_without_unique"],
                },
            ],
        }
        suppressed_issues = review_contract(suppressed_contract)
        assert not any(
            i.get("rule_id") == "multiple_fk_without_unique" for i in suppressed_issues
        )


class TestReviewContractFkDependencyArtifact:
    """Checks that review_contract validates fk_lookup against a dependency artifact."""

    def test_review_contract_fk_no_dep_artifact(self):
        """Existing behavior preserved when no artifact is passed."""
        contract = {
            "tables": [
                {
                    "suggested_model_name": "inventory",
                    "model_name": "Inventory",
                    "columns": [
                        {
                            "source_column": "Crop",
                            "suggested_field_name": "crop",
                            "django_field_class": "models.ForeignKey",
                            "django_field_kwargs": {"to": "Crop"},
                        },
                    ],
                    "str_template": "{self.crop}",
                    "bundle_worksheet_title": "Inventory",
                    "import_config": {
                        "fk_lookup": {
                            "crop": {"model": "Crop", "on": "name"},
                        },
                    },
                },
            ],
        }
        issues_without = review_contract(contract)
        issues_with_none = review_contract(contract, dependency_artifact=None)
        assert issues_without == issues_with_none

    def test_review_contract_fk_with_graph_no_issues(self):
        """Tab has cross-sheet edges matching its fk_lookup — no issue raised."""
        contract = {
            "tables": [
                {
                    "suggested_model_name": "inventory",
                    "model_name": "Inventory",
                    "columns": [
                        {
                            "source_column": "Crop",
                            "suggested_field_name": "crop",
                            "django_field_class": "models.ForeignKey",
                            "django_field_kwargs": {"to": "Crop"},
                        },
                    ],
                    "str_template": "{self.crop}",
                    "bundle_worksheet_title": "Inventory",
                    "import_config": {
                        "fk_lookup": {
                            "crop": {"model": "Crop", "on": "name"},
                        },
                    },
                },
            ],
        }
        artifact = {
            "sheet_graph": {
                "edges": [
                    {"from_sheet": "Inventory", "to_sheet": "Crop", "weight": 1},
                ],
            },
        }
        issues = review_contract(contract, dependency_artifact=artifact)
        assert not any(
            i.get("rule_id") == "fk_lookup_no_cross_sheet_edge" for i in issues
        )

    def test_review_contract_fk_with_graph_missing_edge(self):
        """Tab has no cross-sheet edges despite declaring fk_lookup — issue raised."""
        contract = {
            "tables": [
                {
                    "suggested_model_name": "inventory",
                    "model_name": "Inventory",
                    "columns": [
                        {
                            "source_column": "Crop",
                            "suggested_field_name": "crop",
                            "django_field_class": "models.ForeignKey",
                            "django_field_kwargs": {"to": "Crop"},
                        },
                    ],
                    "str_template": "{self.crop}",
                    "bundle_worksheet_title": "Inventory",
                    "import_config": {
                        "fk_lookup": {
                            "crop": {"model": "Crop", "on": "name"},
                        },
                    },
                },
            ],
        }
        artifact = {
            "sheet_graph": {
                "edges": [
                    {"from_sheet": "OtherTab", "to_sheet": "Crop", "weight": 1},
                ],
            },
        }
        issues = review_contract(contract, dependency_artifact=artifact)
        assert any(i.get("rule_id") == "fk_lookup_no_cross_sheet_edge" for i in issues)

    def test_review_contract_fk_with_empty_sheet_graph(self):
        """Empty sheet_graph yields no crash and no issue."""
        contract = {
            "tables": [
                {
                    "suggested_model_name": "inventory",
                    "model_name": "Inventory",
                    "columns": [
                        {
                            "source_column": "Crop",
                            "suggested_field_name": "crop",
                            "django_field_class": "models.ForeignKey",
                            "django_field_kwargs": {"to": "Crop"},
                        },
                    ],
                    "str_template": "{self.crop}",
                    "bundle_worksheet_title": "Inventory",
                    "import_config": {
                        "fk_lookup": {
                            "crop": {"model": "Crop", "on": "name"},
                        },
                    },
                },
            ],
        }
        artifact = {"sheet_graph": {"edges": []}}
        issues = review_contract(contract, dependency_artifact=artifact)
        assert not any(
            i.get("rule_id") == "fk_lookup_no_cross_sheet_edge" for i in issues
        )

        artifact_no_graph = {}
        issues = review_contract(contract, dependency_artifact=artifact_no_graph)
        assert not any(
            i.get("rule_id") == "fk_lookup_no_cross_sheet_edge" for i in issues
        )


def test_validate_contract_tables_with_exceptions():
    """Exception blocks on tables are validated by validate_contract_tables()."""
    contract = {
        "version": "1.3",
        "tables": [
            {
                "model_name": "HarvestOrder",
                "source_tab": "HarvestOrders",
                "columns": [],
                "exceptions": [
                    {
                        "id": "EX-harvest-001",
                        "title": "Insufficient Inventory",
                        "condition": "Planned harvest < committed order quantity",
                        "severity": "warning",
                        "responses": [{"action": "flag_shortfall", "actor": "system"}],
                    },
                    {
                        "id": "",
                        "condition": "Missing id",
                        "severity": "warning",
                    },
                    {
                        "id": "EX-harvest-002",
                        "condition": "",
                        "severity": "warning",
                    },
                    {
                        "id": "EX-harvest-003",
                        "condition": "Bad severity",
                        "severity": "critical",
                    },
                ],
            }
        ],
    }
    from workbook.codegen.contract import validate_contract_tables

    warnings = validate_contract_tables(contract)
    assert any("missing id" in w for w in warnings), (
        f"Expected warning about missing id, got: {warnings}"
    )
    assert any("missing condition" in w for w in warnings), (
        f"Expected warning about missing condition, got: {warnings}"
    )
    assert any("invalid severity" in w for w in warnings), (
        f"Expected warning about invalid severity, got: {warnings}"
    )
