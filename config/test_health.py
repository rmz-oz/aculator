from django.test import TestCase


class HealthTests(TestCase):
    def test_healthz(self):
        response = self.client.get("/healthz/")
        self.assertEqual(response.json(), {"status": "ok"})
