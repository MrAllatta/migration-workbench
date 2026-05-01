"""Route bundle configs to the correct provider adapter.

The workbench supports multiple upstream sources (Google Sheets, Coda, …).
:func:`build_provider_adapter` reads the ``provider`` key from a bundle config
dict and returns the appropriate :class:`~connectors.base.ProviderAdapter`
subclass, keeping all provider-dispatch logic in one place.
"""

from django.core.management.base import CommandError

from connectors.coda import CodaAdapter
from connectors.google_provider import GoogleSheetsAdapter


def build_provider_adapter(config: dict):
    """Instantiate and return the provider adapter for *config*.

    Args:
        config: Bundle-level config dict.  Must contain a ``"provider"`` key
            whose value is one of ``"google_sheets"`` (default) or ``"coda"``.
            Additional keys are passed through to the adapter constructor.

    Returns:
        ProviderAdapter: Concrete adapter ready to call
        :meth:`~connectors.base.ProviderAdapter.fetch_tab_rows`.

    Raises:
        CommandError: If ``config["provider"]`` is not a recognised value.
    """
    provider = (config.get("provider") or "google_sheets").strip().casefold()
    if provider == "google_sheets":
        return GoogleSheetsAdapter(config)
    if provider == "coda":
        return CodaAdapter(config)
    raise CommandError(f"Unsupported provider '{provider}' (expected google_sheets or coda)")
