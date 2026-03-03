from src.resources.database.entity import Database


class TestDatabase:

    def __init__(self):
        self.database = Database()
        self.database.reset_db()
        self.test_create_analysis()
        self.test_get_analysis()
        self.test_update_analysis()
        self.test_delete_analysis()
        self.tearDown()

    def tearDown(self):
        self.database.close()

    def test_create_analysis(self):
        analysis = self.database.create_analysis(analysis_id="123", image_registry_address="harbor.com",
                                                 ports=[80, 443], pod_ids=["a1"], status="running")
        print(f"{analysis.analysis_id}, 123")

    def test_get_analysis(self):
        analysis = self.database.create_analysis(analysis_id="456", image_registry_address="harbor.com",
                                                 ports=[80, 443], pod_ids=["pod1", "pod2"], status="Running")
        retrieved_analysis = self.database.get_analysis("456")
        print(f"{retrieved_analysis.analysis_id}, 456")
        print(f"{retrieved_analysis.pod_ids}, ['pod1', 'pod2']")

    def test_update_analysis(self):
        analysis = self.database.create_analysis(analysis_id="789", image_registry_address="harbor.com",
                                                 ports=[80, 443], pod_ids=["pod1", "pod2"], status="Running")
        updated_analysis = self.database.update_analysis("789", image_registry_address="harbor.com",
                                                         ports=[80, 443], status="Completed")
        print(f"{updated_analysis.status}, Completed")

    def test_delete_analysis(self):
        analysis = self.database.create_analysis(analysis_id="999", image_registry_address="harbor.com",
                                                 ports=[80, 443], pod_ids=["pod1", "pod2"], status="Completed")
        self.database.delete_analysis("999")
        deleted_analysis = self.database.get_analysis("999")
        print(f"{deleted_analysis}, None")
