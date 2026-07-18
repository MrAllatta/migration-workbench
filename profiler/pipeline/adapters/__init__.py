"""Corpus pipeline adapter package.

Re-exports all concrete adapter implementations for the
:class:`~profiler.pipeline.base.CorpusPipeline` protocol.
"""

from __future__ import annotations

from profiler.pipeline.adapters.coda import CodaCorpusAdapter
from profiler.pipeline.adapters.sheets import SheetsCorpusAdapter

__all__ = ["CodaCorpusAdapter", "SheetsCorpusAdapter"]
