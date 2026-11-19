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
from django.contrib.auth.models import Group
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import tag
from django.urls import reverse

from grading import test_scoring
from grading.access import INSTRUCTOR, STUDENT
from grading.materialized_views import refresh_materialized_views
from grading.models import Enrollment, Grade

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
        self.elif_.set_password(PASSWORD)
        self.elif_.save()
        self.elif_.groups.add(Group.objects.get_or_create(name=STUDENT)[0])
        users = get_user_model().objects
        self.head = users.create_superuser("head", password=PASSWORD)
        self.teacher = users.create_user("ayse", password=PASSWORD, first_name="Ayşe", last_name="Kaya")
        self.teacher.groups.add(Group.objects.get_or_create(name=INSTRUCTOR)[0])
        self.offering.instructors.add(self.teacher)
        self.can = users.create_user("20230002", first_name="Can", last_name="Arslan")
        Enrollment.objects.create(offering=self.offering, student=self.can)
        refresh_materialized_views()
        self.context = self.browser.new_context(viewport={"width": 1280, "height": 800})
        self.page = self.context.new_page()

    def tearDown(self):
        self.context.close()

    def report_url(self):
        return self.live_server_url + reverse("course_report", args=[self.offering.pk])

    def log_in(self, username, next_url=""):
        self.page.goto(f"{self.live_server_url}{reverse('login')}?next={next_url}")
        self.page.get_by_label("Username").fill(username)
        self.page.get_by_label("Password").fill(PASSWORD)
        self.page.get_by_role("button", name="Sign in").click()

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

    def test_wrong_password_stays_on_the_sign_in_page(self):
        self.page.goto(self.live_server_url + reverse("login"))
        self.shot("0-sign-in")
        self.page.get_by_label("Username").fill("ayse")
        self.page.get_by_label("Password").fill("not-the-password")
        self.page.get_by_role("button", name="Sign in").click()

        expect(self.page.get_by_role("alert")).to_have_text("Wrong username or password.")

    def test_instructor_imports_grades_with_preview_and_absence(self):
        self.log_in("ayse")

        expect(self.page.get_by_role("heading", level=1)).to_have_text("Your courses")
        self.shot("5-instructor-home")
        self.page.get_by_role("link", name="Import grades for CSE311 Midterm").click()

        csv = SHOTS / "midterm.csv"
        csv.write_text("student_number;score\nelif;70,0\n")
        self.page.get_by_label("CSV files").set_input_files(csv)
        expect(self.page.locator("#chosen")).to_contain_text("midterm.csv")
        self.shot("6-import-chosen")
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.shot("6b-import-phone")
        self.page.set_viewport_size({"width": 1280, "height": 800})
        self.page.get_by_role("button", name="Preview", exact=True).click()

        expect(self.page.get_by_text("1 grade will be saved, 1 of them replacing an existing grade.")).to_be_visible()
        self.assertEqual(Grade.objects.get(enrollment=self.enrollment, assessment=self.midterm).score, Decimal(90))
        self.page.get_by_label("20230002 was absent").check()
        self.shot("7-import-preview")
        self.page.get_by_role("button", name="Confirm and save").click()

        expect(self.page.get_by_role("status")).to_contain_text("1 grade saved, 1 student marked absent.")
        self.shot("8-import-saved")
        self.page.get_by_role("link", name="Open the class report").click()

        # Same arithmetic as the admin flow: midterm 70 gives PO1 75.0.
        expect(self.po1_cell()).to_have_text("75.0")
        self.assertEqual(Grade.objects.get(enrollment__student=self.can, assessment=self.midterm).status, "absent")
        self.shot("9-report-after-import")

    def test_head_sees_the_report_but_cannot_import(self):
        self.log_in("head")

        expect(self.page.get_by_role("heading", level=1)).to_have_text("Every course in the department")
        expect(self.page.get_by_role("link", name="Import grades for CSE311 Midterm")).to_have_count(0)
        response = self.page.goto(self.live_server_url + reverse("grade_import", args=[self.midterm.pk]))
        self.assertEqual(response.status, 404)

    def test_student_signs_in_to_their_profile_and_not_the_report(self):
        self.log_in("elif")

        expect(self.page.get_by_role("heading", level=1)).to_have_text("Elif Demir")
        expect(self.page.locator(".outcome").first).to_contain_text("PO1")
        self.shot("10-student-profile")
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.shot("11-student-profile-phone")

        response = self.page.goto(self.report_url())
        self.assertEqual(response.status, 404)
        expect(self.page.get_by_text("Demir")).to_have_count(0)
        self.shot("4-student-gets-404")
