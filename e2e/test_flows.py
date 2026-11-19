"""End to end tests in a real browser (#44).

Run with `python manage.py test e2e` after `pip install -r requirements-e2e.txt`
and `playwright install chromium`. Screenshots go to E2E_SCREENSHOTS
(default: e2e-screenshots/), CI uploads them as an artifact.

Without Playwright installed these tests are skipped, so the normal test run
does not need a browser.
"""

import os
from decimal import Decimal
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, tag
from django.urls import reverse

from grading import test_scoring
from grading.models import Grade

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:
    sync_playwright = None

SHOTS = Path(os.environ.get("E2E_SCREENSHOTS", settings.BASE_DIR / "e2e-screenshots"))
PASSWORD = "e2e-password-1"


@tag("e2e")
@skipUnless(sync_playwright, "playwright is not installed")
class BrowserFlowTests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        # Playwright's sync API runs an event loop in this thread; Django refuses
        # ORM calls from such a thread unless this is set.
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
        super().setUpClass()
        SHOTS.mkdir(parents=True, exist_ok=True)
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        super().tearDownClass()

    def setUp(self):
        # Same numbers as the guidelines example: Elif, PO1 85.0.
        test_scoring.ElifExampleTests.setUpTestData.__func__(self)
        self.elif_.first_name, self.elif_.last_name = "Elif", "Demir"
        self.elif_.save()
        users = get_user_model().objects
        self.head = users.create_superuser("head", password=PASSWORD)
        self.context = self.browser.new_context(viewport={"width": 1280, "height": 800})
        self.page = self.context.new_page()

    def tearDown(self):
        self.context.close()

    def report_url(self):
        return self.live_server_url + reverse("course_report", args=[self.offering.pk])

    def log_in(self, username, next_url):
        self.page.goto(f"{self.live_server_url}/admin/login/?next={next_url}")
        self.page.get_by_label("Username").fill(username)
        self.page.get_by_label("Password").fill(PASSWORD)
        self.page.get_by_role("button", name="Log in").click()

    def shot(self, name):
        self.page.screenshot(path=SHOTS / f"{name}.png", full_page=True)

    def po1_cell(self):
        """Elif's cell in the PO1 column, found by the header text, not by position."""
        headers = self.page.locator("thead th").all_inner_texts()
        column = [h.strip() for h in headers].index("PO1")
        row = self.page.get_by_role("row").filter(has_text="Demir")
        return row.locator("th, td").nth(column)

    def test_head_logs_in_and_reads_the_course_report(self):
        self.log_in("head", reverse("course_report", args=[self.offering.pk]))

        expect(self.page.get_by_role("heading", level=1)).to_contain_text("CSE311")
        expect(self.po1_cell()).to_have_text("85.0")
        self.shot("1-course-report")

    def test_changed_grade_shows_up_in_the_report(self):
        grade = Grade.objects.get(enrollment=self.enrollment, assessment=self.midterm)
        self.log_in("head", reverse("admin:grading_grade_change", args=[grade.pk]))

        self.page.get_by_label("Score").fill("70")
        self.shot("2-grade-entry")
        self.page.get_by_role("button", name="Save", exact=True).click()
        expect(self.page.locator(".messagelist")).to_contain_text("was changed successfully")

        # LO1 = 0.6 * 70 + 0.4 * 80 = 74, LO2 = (0.4 * 70 + 80) / 1.4, PO1 = (2 * LO1 + LO2) / 3 = 75.048
        self.page.goto(self.report_url())
        expect(self.po1_cell()).to_have_text("75.0")
        self.assertEqual(Grade.objects.get(pk=grade.pk).score, Decimal(70))
        self.shot("3-course-report-after-change")

    def test_student_cannot_open_the_course_report(self):
        # There is no login page for students yet (#77), so reuse a session
        # made by Django's test client.
        client = Client()
        client.force_login(self.elif_)
        cookie = client.cookies[settings.SESSION_COOKIE_NAME]
        self.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": cookie.value,
            "url": self.live_server_url,
        }])

        response = self.page.goto(self.report_url())

        self.assertEqual(response.status, 404)
        expect(self.page.get_by_text("Demir")).to_have_count(0)
        self.shot("4-student-gets-404")
