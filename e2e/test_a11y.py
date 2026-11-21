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

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.management import call_command
from django.test import override_settings, tag
from django.urls import reverse

from .test_flows import sync_playwright

if sync_playwright:
    from playwright.sync_api import expect

# Test only, so it lives here and not under static/, where collectstatic would ship it.
AXE_JS = (Path(__file__).parent / "vendor/axe-4.14.1.min.js").read_text()
# "serious" is the issue's own bar; "critical" is strictly worse and fails too.
FAILS_ON = {"serious", "critical"}


@tag("e2e")
@skipUnless(sync_playwright, "playwright is not installed")
@override_settings(DEMO=True)
class AccessibilityTests(StaticLiveServerTestCase):
    viewport = (1280, 800)

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
        self.context = self.browser.new_context(viewport={"width": self.viewport[0], "height": self.viewport[1]})
        self.page = self.context.new_page()

    def tearDown(self):
        self.context.close()

    def check(self, label):
        """Run axe on the current page; fail with a readable report if anything serious turns up."""
        # axe has no reflow rule (WCAG 1.4.10): the page itself must not scroll sideways.
        overflow = self.page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
        if overflow > 0:
            self.fail(f"{label} ({self.page.url}) is {overflow}px wider than a {self.viewport[0]}px screen")
        self.page.wait_for_load_state("networkidle")
        self.page.evaluate("() => document.fonts.ready.then(() => new Promise(requestAnimationFrame))")
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
        # On a narrow screen the chart gives way to a note; the tables stay.
        expect(self.page.locator("#slope:visible, .slope-narrow:visible").first).to_be_visible()
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

    def test_profile_and_po_detail_opened_from_the_report(self):
        # The report links each student to their profile; the head and the
        # instructor see a different set of courses there than the student.
        for role in ("Instructor", "Head of department"):
            with self.subTest(role=role):
                self.sign_in_as(role)
                self.page.get_by_role("link", name="report", exact=False).first.click()
                self.page.locator("tbody th a").first.click()
                expect(self.page.get_by_role("heading", level=1)).to_be_visible()
                self.check(f"student profile, {role}")
                self.page.locator(".outcome a.score").first.click()
                expect(self.page.locator("#slope:visible, .slope-narrow:visible").first).to_be_visible()
                self.check(f"PO detail, {role}")

    def test_head_home_and_report(self):
        self.sign_in_as("Head of department")
        expect(self.page.get_by_role("heading", level=1)).to_have_text("Every course in the department")
        self.check("head home")

        self.page.get_by_role("link", name="report", exact=False).first.click()
        self.check("course report, head")


class NarrowAccessibilityTests(AccessibilityTests):
    """The same pages at 320px, the width WCAG 1.4.10 (reflow) is defined at:
    tables scroll sideways here, and a scrolling region a keyboard cannot
    reach only shows up on a narrow screen."""

    viewport = (320, 800)
