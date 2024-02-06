_EXTERNAL_SAVE_PATH = ''


class Database:
    entries: dict[str: list[str]]

    def __int__(self):
        with open(_EXTERNAL_SAVE_PATH, 'r') as f:
            if f.read():
                pass  # TODO: Read database from external save

    def get_analysis_ids(self) -> list[str]:
        return self.entries.keys()

    def get_pod_ids(self, analysis_id: str) -> list[str]:
        return self.entries[analysis_id]

    def add_entry(self, analysis_id: str, pod_ids: list[str]) -> None:
        self.entries[analysis_id] = pod_ids
        # TODO: Update external save

    def delete_entry(self, analysis_id: str) -> None:
        del self.entries[analysis_id]
        # TODO: Update external save (?)
