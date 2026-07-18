"""Abstract base for corpus profiling pipelines.

A corpus pipeline orchestrates a full profiling run over a collection of
data sources (Google Sheets workbooks, Coda docs, etc.) through a
standard phase lifecycle:

1. Discovery — enumerate sources and containers.
2. Indexing — filter and organize sources into a canonical index.
3. Broad profile — lightweight metadata scan of each container.
4. Selection — heuristic scoring, shortlisting, auto-selection, overrides.
5. Deep profile — detailed per-container analysis.
6. Column candidates — extract, score, and enrich columns.
7. Artifact persistence — write all intermediate results.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class CorpusPipeline(ABC):
    """Provider-agnostic corpus profiling pipeline protocol.

    Concrete adapters (e.g. Sheets, Coda) implement each phase method.
    The :meth:`run` method orchestrates all phases and returns a mapping
    from artifact role to persisted file path.
    """

    @abstractmethod
    def discover(self, config: dict[str, Any]) -> dict[str, Any]:
        """Phase 1 — enumerate sources and containers.

        Args:
            config: Parsed corpus configuration dict.

        Returns:
            Discovery payload (provider-specific shape).
        """

    @abstractmethod
    def build_index(
        self, discovery: dict[str, Any], config: dict[str, Any]
    ) -> dict[str, Any]:
        """Phase 2 — filter and organize into a canonical index.

        Args:
            discovery: Output from :meth:`discover`.
            config: Parsed corpus configuration dict.

        Returns:
            Index payload (provider-specific shape).
        """

    @abstractmethod
    def broad_profile(
        self, index: dict[str, Any], config: dict[str, Any]
    ) -> dict[str, Any]:
        """Phase 3 — lightweight metadata scan.

        Args:
            index: Output from :meth:`build_index`.
            config: Parsed corpus configuration dict.

        Returns:
            Broad-profile payload (provider-specific shape).
        """

    @abstractmethod
    def select(
        self,
        broad_profile: dict[str, Any],
        index: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Phase 4 — score, shortlist, auto-select, and apply overrides.

        Args:
            broad_profile: Output from :meth:`broad_profile`.
            index: Output from :meth:`build_index` (for source metadata).
            config: Parsed corpus configuration dict.

        Returns:
            Selection payload including ``approved_*`` mapping.
        """

    @abstractmethod
    def deep_profile(
        self,
        selection: dict[str, Any],
        index: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Phase 5 — detailed per-container analysis.

        Args:
            selection: Output from :meth:`select`.
            index: Output from :meth:`build_index`.
            config: Parsed corpus configuration dict.

        Returns:
            Deep-profile payload including per-container results.
        """

    @abstractmethod
    def derive_columns(
        self, deep_results: dict[str, Any], config: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Phase 6 — extract and score column candidates.

        Args:
            deep_results: Output from :meth:`deep_profile`.
            config: Parsed corpus configuration dict.

        Returns:
            List of column candidate dicts.
        """

    @abstractmethod
    def enrich_columns(self, columns: list[dict[str, Any]]) -> None:
        """Enrich column candidates in-place with computed / FK / key metadata.

        Args:
            columns: Column candidate dicts to mutate in-place.
        """

    @abstractmethod
    def run(
        self, config: dict[str, Any], out_dir: Path, date_stamp: str
    ) -> dict[str, str]:
        """Execute the full pipeline and return artifact path mapping.

        Args:
            config: Parsed corpus configuration dict.
            out_dir: Directory where JSON artifacts are written.
            date_stamp: Timestamp suffix for artifact filenames.

        Returns:
            dict[str, str]: Mapping from artifact role to file path.
        """
