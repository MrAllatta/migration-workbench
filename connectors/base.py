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

    def fetch_tab_structure(self, tab_config: dict) -> dict | None:
        """Return UI/structural metadata for a single tab.

        This is an optional, additive companion to :meth:`fetch_tab_rows`.
        Adapters that have not yet implemented a structural pass should leave
        the default ``None`` return in place so callers (e.g. ``pull_bundle
        --include-structure``) can silently skip them.

        Args:
            tab_config: Same shape as the dict passed to :meth:`fetch_tab_rows`.
                Callers may inject already-resolved identifiers (for example
                ``spreadsheet_id``) so the adapter does not need to re-resolve
                names.

        Returns:
            dict | None: Per-tab structural envelope conforming to the
            ``structure-draft-1`` shape (``worksheet_title``, ``columns``,
            ``hidden``, ...) when the adapter supports it; ``None`` otherwise.
        """
        return None
