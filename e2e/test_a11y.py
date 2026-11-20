"""axe-core runs against every page and fails on serious issues (#45).

Uses the demo role switcher (#46) to reach every role without hand-built
fixtures, then follows the same links a user would to reach the two chart
pages: the PO rings on the student profile and the slopegraph on the PO
detail page. Both already have a table view for screen readers and printing;
this is what keeps that true.
"""

import os
from io import StringIO
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.management import call_command
from django.test import override_settings, tag
from django.urls import reverse

from .test_flows import sync_playwright

if sync_playwright:
    from playwright.sync_api import expect

AXE_JS = (Path(settings.BASE_DIR) / "grading/static/vendor/axe-4.14.1.min.js").read_text()
# "serious" is the issue's own bar; "critical" is strictly worse and fails too.
FAILS_ON = {"serious", "critical"}


@tag("e2e")
@skipUnless(sync_playwright, "playwright is not installed")
@override_settings(DEMO=True)
class AccessibilityTests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        # Playwright's sync API runs an event loop in this thread; Django refuses
        # ORM calls from such a thread unless this is set.
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        super().tearDownClass()

    def setUp(self):
        # --clean: the realistic scenarios (#100) assume fake_data's default
        # 400 students; at 5 they can find too few candidates for a scenario
        # and crash (same as test_demo.py).
        call_command("demo_data", "--clean", students=5, stdout=StringIO())
        self.context = self.browser.new_context(viewport={"width": 1280, "height": 800})
        self.page = self.context.new_page()

    def tearDown(self):
        self.context.close()

    def check(self, label):
        """Run axe on the current page; fail with a readable report if anything serious turns up."""
        self.page.add_script_tag(content=AXE_JS)
        results = self.page.evaluate("() => axe.run()")
        serious = [v for v in results["violations"] if v["impact"] in FAILS_ON]
        if not serious:
            return
        report = "\n".join(
            f"- [{v['impact']}] {v['id']}: {v['help']} ({len(v['nodes'])} element(s)) {v['helpUrl']}"
            for v in serious
        )
        self.fail(f"{label} ({self.page.url}):\n{report}")

    def sign_in_as(self, role_label):
        self.page.goto(self.live_server_url + reverse("login"))
        self.check("login page")
        self.page.get_by_role("group", name="Demo, sign in as").get_by_role("button", name=role_label).click()

    def test_login_page_before_signing_in(self):
        self.page.goto(self.live_server_url + reverse("login"))
        self.check("login page")

    def test_student_profile_and_po_detail(self):
        self.sign_in_as("Student")
        expect(self.page.get_by_role("heading", level=1)).to_be_visible()
        self.check("student profile")

        # The first PO that has a real score, not "thin" or missing evidence.
        scored = self.page.locator(".outcome a.score").first
        scored.click()
        expect(self.page.locator("#slope")).to_be_visible()
        self.check("PO detail")

    def test_instructor_home_report_and_import(self):
        self.sign_in_as("Instructor")
        expect(self.page.get_by_role("heading", level=1)).to_have_text("Your courses")
        self.check("instructor home")

        self.page.get_by_role("link", name="report", exact=False).first.click()
        expect(self.page.get_by_role("heading", level=1)).to_be_visible()
        self.check("course report")

        self.page.go_back()
        self.page.get_by_role("link", name="Import grades for", exact=False).first.click()
        self.check("grade import")

    def test_head_home_and_report(self):
        self.sign_in_as("Head of department")
        expect(self.page.get_by_role("heading", level=1)).to_have_text("Every course in the department")
        self.check("head home")

        self.page.get_by_role("link", name="report", exact=False).first.click()
        self.check("course report, head")
