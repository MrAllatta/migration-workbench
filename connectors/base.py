"""Abstract base for workbook data-source adapters.

All provider integrations (Google Sheets, Coda, …) implement
:class:`ProviderAdapter`.  The workbench routes to the correct concrete
adapter at runtime via :func:`~connectors.router.build_provider_adapter`.
"""

from abc import ABC, abstractmethod


class ProviderAdapter(ABC):
    """Contract for data-source connectors that return raw tab rows.

    Each adapter is responsible for authenticating to its upstream provider,
    fetching the requested tab's rows, and returning them in the normalised
    ``{"rows": [[...], ...], ...}`` envelope understood by the workbench
    connector pipeline.
    """

    @abstractmethod
    def fetch_tab_rows(self, tab_config: dict) -> dict:
        """Fetch raw rows for a single tab from the upstream source.

        Args:
            tab_config: Tab-level config dict from the bundle JSON.  Must
                include at minimum the keys needed to identify the tab within
                the source document (e.g. ``worksheet_title`` for Google
                Sheets, ``table_id`` for Coda).

        Returns:
            dict: Envelope containing at least a ``"rows"`` key whose value is
            a list of lists (header row first), plus any provider-specific
            metadata (e.g. ``"spreadsheet_id"``, ``"tab_id"``).
        """
