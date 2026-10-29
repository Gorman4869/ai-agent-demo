import unittest

from fastapi.testclient import TestClient

from backend.app.review_demo import create_demo_review_app


class ReviewDemoBoundaryTest(unittest.TestCase):
    def test_only_loopback_client_and_known_host_are_accepted(self) -> None:
        with TestClient(create_demo_review_app(), client=("127.0.0.1", 12345), base_url="http://127.0.0.1") as client:
            self.assertEqual(200, client.get("/health").status_code)
            self.assertEqual(400, client.get("/health", headers={"Host": "outside.example"}).status_code)
        with TestClient(create_demo_review_app(), client=("192.0.2.1", 12345), base_url="http://127.0.0.1") as client:
            self.assertEqual(403, client.get("/health").status_code)
