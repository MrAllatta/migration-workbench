from connectors.base import ProviderAdapter


class CodaAdapter(ProviderAdapter):
    def __init__(self, config: dict):
        self.config = config

    def fetch_tab_rows(self, tab_config: dict) -> dict:
        raise NotImplementedError(
            "Coda provider support is planned but not yet implemented. "
            "Expected tab keys include doc_id, table_id, and optional view_id."
        )
