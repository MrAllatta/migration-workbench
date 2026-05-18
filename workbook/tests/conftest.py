"""Shared test helpers for workbook tests."""

from __future__ import annotations

from typing import Any


def make_table(suggested_model_name: str, **overrides: Any) -> dict[str, Any]:
    """Build a minimal contract table dict with required fields.

    Derives model_name from suggested_model_name using PascalCase
    (snake_case input -> PascalCase output).
    """
    model_name = "".join(
        p.capitalize() for p in suggested_model_name.replace("-", "_").split("_")
    )
    return {
        "suggested_model_name": suggested_model_name,
        "model_name": model_name,
        **overrides,
    }
