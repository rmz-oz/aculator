"""The demo role switcher in a real browser (#46)."""

import os
from io import StringIO
from unittest import skipUnless

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.management import call_command
from django.test import override_settings, tag
from django.urls import reverse

from .test_flows import SHOTS, sync_playwright

if sync_playwright:
    from playwright.sync_api import expect


@tag("e2e")
@skipUnless(sync_playwright, "playwright is not installed")
@override_settings(DEMO=True)
class DemoSwitcherFlowTests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
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
        call_command("demo_data", "--clean", students=5, stdout=StringIO())
        self.context = self.browser.new_context(viewport={"width": 1280, "height": 800})
        self.page = self.context.new_page()

    def tearDown(self):
        self.context.close()

    def test_one_click_per_role(self):
        page = self.page
        page.goto(self.live_server_url + reverse("login"))
        demo = page.get_by_role("group", name="Demo, sign in as")
        self.shot("7-demo-sign-in")

        demo.get_by_role("button", name="Student").click()
        expect(page.get_by_role("heading", level=1)).to_have_text("Student1 Demo")
        self.shot("8-demo-student")

        switcher = page.get_by_role("group", name="View as")
        expect(switcher.get_by_role("button", name="Student")).to_have_attribute("aria-current", "true")
        switcher.get_by_role("button", name="Instructor").click()
        expect(page.get_by_role("heading", level=1)).to_have_text("Your courses")
        expect(page.locator("main")).to_contain_text("CSE301")
        expect(page.locator("main")).not_to_contain_text("CSE101")

        page.get_by_role("group", name="View as").get_by_role("button", name="Head of department").click()
        expect(page.get_by_role("heading", level=1)).to_have_text("Every course in the department")
        expect(page.locator("main")).to_contain_text("CSE101")
        self.shot("9-demo-head")

        page.get_by_role("button", name="Sign out").click()
        expect(page.get_by_role("group", name="Demo, sign in as")).to_be_visible()

    def shot(self, name):
        self.page.screenshot(path=SHOTS / f"{name}.png", full_page=True)
