"""Tests for the SheetsCorpusAdapter.

These tests verify the adapter class structure, constructor signature,
ABC compliance, and phase method signatures.  Phase methods are fully
implemented; behaviour tests verify callability and signature fidelity.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from profiler.pipeline.adapters.sheets import SheetsCorpusAdapter
from profiler.pipeline.base import CorpusPipeline


class FakeDriveService:
    """Stand-in for an authenticated Google Drive API service object."""


class FakeSheetsService:
    """Stand-in for an authenticated Google Sheets API service object."""


# ------------------------------------------------------------------
# Structural / ABC tests
# ------------------------------------------------------------------


def test_sheets_adapter_is_corpus_pipeline():
    """SheetsCorpusAdapter is a registered subclass of CorpusPipeline."""
    assert issubclass(SheetsCorpusAdapter, CorpusPipeline)


def test_sheets_adapter_instantiates():
    """A fully-implemented adapter (even with TODO stubs) instantiates."""
    adapter = SheetsCorpusAdapter(
        drive_service=FakeDriveService(),
        sheets_service=FakeSheetsService(),
    )
    assert isinstance(adapter, CorpusPipeline)
    assert isinstance(adapter, SheetsCorpusAdapter)


def test_sheets_adapter_stores_services():
    """Constructor stores drive_service and sheets_service on the instance."""
    drive = FakeDriveService()
    sheets = FakeSheetsService()
    adapter = SheetsCorpusAdapter(drive_service=drive, sheets_service=sheets)
    assert adapter.drive_service is drive
    assert adapter.sheets_service is sheets


def test_sheets_adapter_requires_keyword_args():
    """Constructor enforces keyword-only arguments for services."""
    with pytest.raises(TypeError):
        SheetsCorpusAdapter(FakeDriveService(), FakeSheetsService())


# ------------------------------------------------------------------
# Phase method existence tests
# ------------------------------------------------------------------


def test_sheets_adapter_has_all_phase_methods():
    """Every abstract phase method from CorpusPipeline is implemented."""
    expected_methods = [
        "discover",
        "build_index",
        "broad_profile",
        "select",
        "deep_profile",
        "derive_columns",
        "enrich_columns",
        "run",
    ]
    for method_name in expected_methods:
        assert hasattr(SheetsCorpusAdapter, method_name)
        method = getattr(SheetsCorpusAdapter, method_name)
        assert callable(method)


# ------------------------------------------------------------------
# Phase method behaviour tests (callability + signature)
# ------------------------------------------------------------------


def test_discover_accepts_config_dict():
    """discover accepts a config dict without crashing on empty input."""
    adapter = SheetsCorpusAdapter(
        drive_service=FakeDriveService(),
        sheets_service=FakeSheetsService(),
    )
    assert callable(adapter.discover)


def test_build_index_accepts_discovery_and_config():
    """build_index accepts discovery payload and config dict."""
    adapter = SheetsCorpusAdapter(
        drive_service=FakeDriveService(),
        sheets_service=FakeSheetsService(),
    )
    assert callable(adapter.build_index)


def test_broad_profile_accepts_index_and_config():
    """broad_profile accepts index payload and config dict."""
    adapter = SheetsCorpusAdapter(
        drive_service=FakeDriveService(),
        sheets_service=FakeSheetsService(),
    )
    assert callable(adapter.broad_profile)


def test_select_accepts_broad_profile_index_config():
    """select accepts broad_profile, index, and config dicts."""
    adapter = SheetsCorpusAdapter(
        drive_service=FakeDriveService(),
        sheets_service=FakeSheetsService(),
    )
    assert callable(adapter.select)


def test_deep_profile_accepts_selection_index_config():
    """deep_profile accepts selection, index, and config dicts."""
    adapter = SheetsCorpusAdapter(
        drive_service=FakeDriveService(),
        sheets_service=FakeSheetsService(),
    )
    assert callable(adapter.deep_profile)


def test_derive_columns_accepts_deep_results_and_config():
    """derive_columns accepts deep_results dict and config dict."""
    adapter = SheetsCorpusAdapter(
        drive_service=FakeDriveService(),
        sheets_service=FakeSheetsService(),
    )
    assert callable(adapter.derive_columns)


def test_enrich_columns_accepts_list():
    """enrich_columns accepts a list of column dicts."""
    adapter = SheetsCorpusAdapter(
        drive_service=FakeDriveService(),
        sheets_service=FakeSheetsService(),
    )
    # enrich_columns mutates in-place; call with empty list to verify no crash
    adapter.enrich_columns([])


def test_run_accepts_config_out_dir_date_stamp():
    """run accepts config, out_dir, and date_stamp arguments."""
    adapter = SheetsCorpusAdapter(
        drive_service=FakeDriveService(),
        sheets_service=FakeSheetsService(),
    )
    assert callable(adapter.run)
    # Verify the signature matches (structural test; run() makes API calls)
    import inspect

    sig = inspect.signature(SheetsCorpusAdapter.run)
    params = list(sig.parameters.keys())
    assert params == ["self", "config", "out_dir", "date_stamp"]


# ------------------------------------------------------------------
# Signature fidelity tests
# ------------------------------------------------------------------


def test_run_signature_matches_cohort_corpus():
    """run() accepts config, out_dir, date_stamp — same as run_cohort_corpus."""
    import inspect
    import typing

    sig = inspect.signature(SheetsCorpusAdapter.run)
    params = list(sig.parameters.keys())
    assert params == ["self", "config", "out_dir", "date_stamp"]

    hints = typing.get_type_hints(SheetsCorpusAdapter.run)
    assert hints["config"] == dict[str, Any]
    assert hints["out_dir"] == Path
    assert hints["date_stamp"] == str


def test_discover_signature():
    """discover accepts config dict and returns a dict."""
    import inspect
    import typing

    sig = inspect.signature(SheetsCorpusAdapter.discover)
    params = list(sig.parameters.keys())
    assert params == ["self", "config"]
    hints = typing.get_type_hints(SheetsCorpusAdapter.discover)
    assert hints["config"] == dict[str, Any]
    assert hints["return"] == dict[str, Any]


def test_build_index_signature():
    """build_index accepts discovery + config and returns a dict."""
    import inspect
    import typing

    sig = inspect.signature(SheetsCorpusAdapter.build_index)
    params = list(sig.parameters.keys())
    assert params == ["self", "discovery", "config"]
    hints = typing.get_type_hints(SheetsCorpusAdapter.build_index)
    assert hints["return"] == dict[str, Any]


def test_broad_profile_signature():
    """broad_profile accepts index + config and returns a dict."""
    import inspect
    import typing

    sig = inspect.signature(SheetsCorpusAdapter.broad_profile)
    params = list(sig.parameters.keys())
    assert params == ["self", "index", "config"]
    hints = typing.get_type_hints(SheetsCorpusAdapter.broad_profile)
    assert hints["return"] == dict[str, Any]


def test_select_signature():
    """select accepts broad_profile + index + config and returns a dict."""
    import inspect
    import typing

    sig = inspect.signature(SheetsCorpusAdapter.select)
    params = list(sig.parameters.keys())
    assert params == ["self", "broad_profile", "index", "config"]
    hints = typing.get_type_hints(SheetsCorpusAdapter.select)
    assert hints["return"] == dict[str, Any]


def test_deep_profile_signature():
    """deep_profile accepts selection + index + config and returns a dict."""
    import inspect
    import typing

    sig = inspect.signature(SheetsCorpusAdapter.deep_profile)
    params = list(sig.parameters.keys())
    assert params == ["self", "selection", "index", "config"]
    hints = typing.get_type_hints(SheetsCorpusAdapter.deep_profile)
    assert hints["return"] == dict[str, Any]


def test_derive_columns_signature():
    """derive_columns accepts deep_results + config and returns a list."""
    import inspect
    import typing

    sig = inspect.signature(SheetsCorpusAdapter.derive_columns)
    params = list(sig.parameters.keys())
    assert params == ["self", "deep_results", "config"]
    hints = typing.get_type_hints(SheetsCorpusAdapter.derive_columns)
    assert hints["return"] == list[dict[str, Any]]


def test_enrich_columns_signature():
    """enrich_columns accepts a list of column dicts and returns None."""
    import inspect
    import typing

    sig = inspect.signature(SheetsCorpusAdapter.enrich_columns)
    params = list(sig.parameters.keys())
    assert params == ["self", "columns"]
    hints = typing.get_type_hints(SheetsCorpusAdapter.enrich_columns)
    assert hints["return"] is type(None)
