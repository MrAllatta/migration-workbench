from django.core.management.base import CommandError

from connectors.coda import CodaAdapter
from connectors.google_provider import GoogleSheetsAdapter


def build_provider_adapter(config: dict):
    provider = (config.get("provider") or "google_sheets").strip().casefold()
    if provider == "google_sheets":
        return GoogleSheetsAdapter(config)
    if provider == "coda":
        return CodaAdapter(config)
    raise CommandError(f"Unsupported provider '{provider}' (expected google_sheets or coda)")
