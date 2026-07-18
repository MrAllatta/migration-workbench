"""Corpus pipeline dispatcher and orchestration runner.

Provides a provider-agnostic entry point that routes to the correct
adapter implementation (Sheets or Coda) based on the ``provider`` key
in the corpus configuration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from profiler.pipeline.adapters import CodaCorpusAdapter, SheetsCorpusAdapter


class CorpusPipelineDispatcher:
    """Factory that builds and runs the correct adapter for a corpus config.

    Usage::

        dispatcher = CorpusPipelineDispatcher()
        dispatcher.run(config, out_dir, date_stamp)

    The dispatcher inspects ``config["provider"]`` (``"sheets"`` or
    ``"coda"``) and delegates to the matching adapter's :meth:`run`.
    """

    PROVIDER_SHEETS = "sheets"
    PROVIDER_CODA = "coda"

    def create_adapter(
        self,
        config: dict[str, Any],
        *,
        drive_service: Any = None,
        sheets_service: Any = None,
        session: Any = None,
        resume_from_tab_selection: bool = False,
        resume_from_broad: bool = False,
        stop_before_deep: bool = False,
        skip_existing_deep: bool = False,
        folder_id: str | None = None,
        resume_from_table_selection: bool = False,
    ) -> SheetsCorpusAdapter | CodaCorpusAdapter:
        """Create an adapter instance matching the provider type in *config*.

        Args:
            config: Parsed corpus configuration dict.  Must contain a
                ``provider`` key set to ``"sheets"`` or ``"coda"``.
            drive_service: Authenticated Google Drive API service
                (required for ``"sheets"``).
            sheets_service: Authenticated Google Sheets API service
                (required for ``"sheets"``).
            session: Authenticated ``requests.Session`` for the Coda API
                (required for ``"coda"``).
            resume_from_tab_selection: Sheets-only resume mode.
            resume_from_broad: Sheets-only resume mode.
            stop_before_deep: Stop after tab selection (Sheets) or
                table selection (Coda).
            skip_existing_deep: Reuse cached deep profile files (Sheets).
            folder_id: Google Drive folder ID (Sheets).
            resume_from_table_selection: Coda-only resume mode.

        Returns:
            A configured adapter instance.

        Raises:
            ValueError: If ``provider`` is missing or unsupported.
        """
        provider = config.get("provider", "")
        if provider == self.PROVIDER_SHEETS:
            if drive_service is None or sheets_service is None:
                raise ValueError(
                    "drive_service and sheets_service are required for provider='sheets'"
                )
            return SheetsCorpusAdapter(
                drive_service=drive_service,
                sheets_service=sheets_service,
                resume_from_tab_selection=resume_from_tab_selection,
                resume_from_broad=resume_from_broad,
                stop_before_deep=stop_before_deep,
                skip_existing_deep=skip_existing_deep,
                folder_id=folder_id,
            )
        if provider == self.PROVIDER_CODA:
            if session is None:
                raise ValueError(
                    "session is required for provider='coda'"
                )
            return CodaCorpusAdapter(
                session=session,
                resume_from_table_selection=resume_from_table_selection,
                stop_before_deep=stop_before_deep,
            )
        msg = (
            f"Unsupported provider: {provider!r}. "
            f"Expected one of: {self.PROVIDER_SHEETS!r}, {self.PROVIDER_CODA!r}"
        )
        raise ValueError(msg)

    def run(
        self,
        config: dict[str, Any],
        out_dir: Path,
        date_stamp: str,
        *,
        drive_service: Any = None,
        sheets_service: Any = None,
        session: Any = None,
        resume_from_tab_selection: bool = False,
        resume_from_broad: bool = False,
        stop_before_deep: bool = False,
        skip_existing_deep: bool = False,
        folder_id: str | None = None,
        resume_from_table_selection: bool = False,
    ) -> dict[str, str]:
        """Create and run the correct adapter for *config*.

        Args:
            config: Corpus configuration dict with a ``provider`` key.
            out_dir: Directory for output artifacts.
            date_stamp: ISO timestamp for artifact filenames.
            drive_service: Google Drive API service (sheets provider).
            sheets_service: Google Sheets API service (sheets provider).
            session: Coda API ``requests.Session`` (coda provider).
            resume_from_tab_selection: Sheets-only resume.
            resume_from_broad: Sheets-only resume.
            stop_before_deep: Stop before deep profile phase.
            skip_existing_deep: Reuse cached deep files (Sheets).
            folder_id: Google Drive folder ID (Sheets).
            resume_from_table_selection: Coda-only resume.

        Returns:
            Mapping from artifact role to file path (same as adapter
            :meth:`run`).
        """
        adapter = self.create_adapter(
            config,
            drive_service=drive_service,
            sheets_service=sheets_service,
            session=session,
            resume_from_tab_selection=resume_from_tab_selection,
            resume_from_broad=resume_from_broad,
            stop_before_deep=stop_before_deep,
            skip_existing_deep=skip_existing_deep,
            folder_id=folder_id,
            resume_from_table_selection=resume_from_table_selection,
        )
        return adapter.run(config=config, out_dir=out_dir, date_stamp=date_stamp)
