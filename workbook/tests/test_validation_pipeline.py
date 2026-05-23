from __future__ import annotations

import pytest

from workbook.codegen.validation_pipeline import (
    GlobalValidationError,
    ValidationResult,
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
