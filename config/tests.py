from django.db import connection
from django.test import TestCase


class SmokeTests(TestCase):
    def test_database_is_postgresql(self):
        self.assertEqual(connection.vendor, "postgresql")

    def test_admin_login_page_loads(self):
        response = self.client.get("/admin/login/")
        self.assertEqual(response.status_code, 200)
