from abc import ABC, abstractmethod


class ProviderAdapter(ABC):
    @abstractmethod
    def fetch_tab_rows(self, tab_config: dict) -> dict:
        """Return provider metadata plus raw tab rows."""

