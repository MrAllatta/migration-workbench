"""Tests for the CorpusPipeline abstract base class."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from profiler.pipeline.base import CorpusPipeline


class CompleteAdapter(CorpusPipeline):
    """A fully implemented adapter for instantiation tests."""

    def discover(self, config: dict[str, Any]) -> dict[str, Any]:
        return {"phase": "discover"}

    def build_index(
        self, discovery: dict[str, Any], config: dict[str, Any]
    ) -> dict[str, Any]:
        return {"phase": "index"}

    def broad_profile(
        self, index: dict[str, Any], config: dict[str, Any]
    ) -> dict[str, Any]:
        return {"phase": "broad"}

    def select(
        self,
        broad_profile: dict[str, Any],
        index: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        return {"phase": "select"}

    def deep_profile(
        self,
        selection: dict[str, Any],
        index: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        return {"phase": "deep"}

    def derive_columns(
        self, deep_results: dict[str, Any], config: dict[str, Any]
    ) -> list[dict[str, Any]]:
        return []

    def enrich_columns(self, columns: list[dict[str, Any]]) -> None:
        pass

    def run(
        self, config: dict[str, Any], out_dir: Path, date_stamp: str
    ) -> dict[str, str]:
        return {}


class PartialAdapter(CorpusPipeline):
    """Missing several methods — should fail instantiation."""

    def discover(self, config: dict[str, Any]) -> dict[str, Any]:
        return {}

    def run(
        self, config: dict[str, Any], out_dir: Path, date_stamp: str
    ) -> dict[str, str]:
        return {}


def test_corpus_pipeline_is_abc():
    """CorpusPipeline cannot be instantiated directly."""
    with pytest.raises(TypeError, match="abstract"):
        CorpusPipeline()


def test_corpus_pipeline_concrete_adapter_instantiates():
    """A fully-implemented adapter can be instantiated."""
    adapter = CompleteAdapter()
    assert isinstance(adapter, CorpusPipeline)


def test_corpus_pipeline_partial_adapter_fails():
    """A partially-implemented adapter raises TypeError at init."""
    with pytest.raises(TypeError, match="abstract"):
        PartialAdapter()


def test_corpus_pipeline_phase_methods_exist():
    """All expected phase methods are declared on the base class."""
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
        assert hasattr(CorpusPipeline, method_name)
        method = getattr(CorpusPipeline, method_name)
        assert getattr(method, "__isabstractmethod__", False)


def test_complete_adapter_run():
    """A concrete adapter can execute the run method."""
    adapter = CompleteAdapter()
    result = adapter.run({}, Path("/tmp"), "2026-01-01")
    assert isinstance(result, dict)


def test_complete_adapter_phase_chaining():
    """Individual phase methods return the expected dict/list shapes."""
    adapter = CompleteAdapter()
    config: dict[str, Any] = {}

    discovery = adapter.discover(config)
    assert isinstance(discovery, dict)

    index = adapter.build_index(discovery, config)
    assert isinstance(index, dict)

    broad = adapter.broad_profile(index, config)
    assert isinstance(broad, dict)

    selection = adapter.select(broad, index, config)
    assert isinstance(selection, dict)

    deep = adapter.deep_profile(selection, index, config)
    assert isinstance(deep, dict)

    columns = adapter.derive_columns(deep, config)
    assert isinstance(columns, list)

    adapter.enrich_columns(columns)
