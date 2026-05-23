from __future__ import annotations

import pytest

from workbook.codegen.validation_pipeline import (
    GlobalValidationError,
    ValidationResult,
    partition_contract_on_validation,
)


class TestValidationResult:
    def test_frozen(self):
        result = ValidationResult(
            model_name="Crop",
            check_id="WORKBOOK-CONTRACT-001",
            message="empty model_name",
        )
        with pytest.raises(AttributeError):
            result.model_name = "changed"

    def test_defaults(self):
        result = ValidationResult(
            model_name="Crop",
            check_id="WORKBOOK-CONTRACT-001",
            message="test",
        )
        assert result.action is None
        assert result.severity == "error"

    def test_warning_severity(self):
        result = ValidationResult(
            model_name="Crop",
            check_id="WORKBOOK-CONTRACT-001",
            message="test",
            severity="warning",
        )
        assert result.severity == "warning"

    def test_global_error(self):
        result = ValidationResult(
            model_name=None,
            check_id="WORKBOOK-CONTRACT-000",
            message="no tables key",
        )
        assert result.model_name is None

    def test_literal_severity_rejects_invalid(self):
        with pytest.raises(TypeError):
            ValidationResult(
                model_name="Crop",
                check_id="TEST",
                message="test",
                severity="critical",
            )


class TestGlobalValidationError:
    def test_is_user_facing_error(self):
        from workbench.exceptions import UserFacingError

        err = GlobalValidationError(
            "structure broken",
            check_id="WORKBOOK-CONTRACT-000",
            action="Fix the contract YAML",
        )
        assert isinstance(err, UserFacingError)

    def test_carries_check_id_and_action(self):
        err = GlobalValidationError(
            "no tables key",
            check_id="WORKBOOK-CONTRACT-000",
            action="Add a tables key",
        )
        assert err.check_id == "WORKBOOK-CONTRACT-000"
        assert err.action == "Add a tables key"


class TestPartitionContractOnValidation:
    @pytest.fixture()
    def basic_contract(self):
        return {
            "version": "1.3",
            "source": {},
            "tables": [
                {"model_name": "Crop", "columns": [{"suggested_field_name": "name"}]},
                {"model_name": "SaleItem", "columns": [{"suggested_field_name": "amount"}]},
                {"model_name": "Farm", "columns": [{"suggested_field_name": "name"}]},
            ],
        }

    def test_drops_error_tables(self, basic_contract, tmp_path):
        out_path = tmp_path / "models_auto.py"
        results = [
            ValidationResult(model_name="SaleItem", check_id="TEST-001", message="duplicate"),
        ]
        clean, collector = partition_contract_on_validation(
            basic_contract, results, out_path=out_path,
        )
        assert [t["model_name"] for t in clean["tables"]] == ["Crop", "Farm"]
        assert not collector.is_empty()

    def test_warning_does_not_drop(self, basic_contract, tmp_path):
        out_path = tmp_path / "models_auto.py"
        results = [
            ValidationResult(
                model_name="SaleItem",
                check_id="TEST-WARN",
                message="minor issue",
                severity="warning",
            ),
        ]
        clean, collector = partition_contract_on_validation(
            basic_contract, results, out_path=out_path,
        )
        assert [t["model_name"] for t in clean["tables"]] == ["Crop", "SaleItem", "Farm"]
        assert collector.is_empty()

    def test_rejection_file_derived_from_out_path(self, basic_contract, tmp_path):
        out_path = tmp_path / "backend" / "models_auto.py"
        results = [
            ValidationResult(model_name="SaleItem", check_id="TEST-001", message="bad"),
        ]
        clean, collector = partition_contract_on_validation(
            basic_contract, results, out_path=out_path,
        )
        expected_rejection = tmp_path / "backend" / "models_auto-rejected.yaml"
        assert expected_rejection.exists()

    def test_check_id_carried_through(self, basic_contract, tmp_path):
        out_path = tmp_path / "models_auto.py"
        results = [
            ValidationResult(
                model_name="SaleItem",
                check_id="WORKBOOK-CONTRACT-003",
                message="Duplicate model_name 'SaleItem'",
                action="Rename one of the duplicate tables",
            ),
        ]
        clean, collector = partition_contract_on_validation(
            basic_contract, results, out_path=out_path,
        )
        assert collector.rejected[0].check_id == "WORKBOOK-CONTRACT-003"
        assert collector.rejected[0].action == "Rename one of the duplicate tables"

    def test_raises_global_error(self, basic_contract, tmp_path):
        out_path = tmp_path / "models_auto.py"
        results = [
            ValidationResult(model_name=None, check_id="GLOBAL-001", message="no tables key"),
        ]
        with pytest.raises(GlobalValidationError):
            partition_contract_on_validation(basic_contract, results, out_path=out_path)

    def test_global_warning_does_not_raise(self, basic_contract, tmp_path):
        out_path = tmp_path / "models_auto.py"
        results = [
            ValidationResult(
                model_name=None,
                check_id="GLOBAL-WARN",
                message="minor",
                severity="warning",
            ),
        ]
        clean, collector = partition_contract_on_validation(
            basic_contract, results, out_path=out_path,
        )
        assert len(clean["tables"]) == 3

    def test_no_errors_returns_clean_copy(self, basic_contract, tmp_path):
        out_path = tmp_path / "models_auto.py"
        clean, collector = partition_contract_on_validation(
            basic_contract, [], out_path=out_path,
        )
        assert [t["model_name"] for t in clean["tables"]] == ["Crop", "SaleItem", "Farm"]
        assert collector.is_empty()
