class Database:
    entries: dict[str: list[str]]

    def get_analysis_ids(self) -> list[str]:
        return self.entries.keys()

    def get_pod_ids(self, analysis_id: str) -> list[str]:
        return self.entries[analysis_id]
