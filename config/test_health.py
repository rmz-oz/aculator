import os
from unittest import mock

from django.test import TestCase


class HealthTests(TestCase):
    def test_healthz(self):
        response = self.client.get("/healthz/")
        self.assertEqual(response.json()["status"], "ok")

    def test_healthz_reports_build_commit(self):
        with mock.patch.dict(os.environ, {"GIT_SHA": "abc123"}):
            response = self.client.get("/healthz/")
        self.assertEqual(response.json()["version"], "abc123")
