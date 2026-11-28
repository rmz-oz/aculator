from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from .access import INSTRUCTOR, STUDENT
from .materialized_views import refresh_materialized_views
from .models import (
    Assessment,
    AssessmentLOWeight,
    Course,
    CourseOffering,
    Enrollment,
    Grade,
    LearningOutcome,
    LOPOWeight,
    POComponent,
    ProgramOutcome,
    Term,
)

D = Decimal


class LanguageSwitchTests(TestCase):
    """Turkish and English interface, switched in the header (#49)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="elif")
        self.user.groups.add(Group.objects.get_or_create(name=STUDENT)[0])

    def test_browser_language_is_used_without_signing_in(self):
        response = self.client.get(reverse("login"), HTTP_ACCEPT_LANGUAGE="tr")
        self.assertContains(response, "Giriş yap")

    def test_browser_language_defaults_to_english(self):
        response = self.client.get(reverse("login"), HTTP_ACCEPT_LANGUAGE="de")
        self.assertContains(response, "Sign in")

    def test_switching_in_the_header_persists_across_requests(self):
        self.client.force_login(self.user)
        self.client.post(reverse("set_language"), {"language": "tr", "next": "/"})

        # home redirects a student to their own profile; the switch should
        # still hold there, since it lives in the session, not the page.
        response = self.client.get(reverse("home"), follow=True)

        self.assertContains(response, "Çıktılarım")  # "My outcomes"
        self.assertContains(response, "TR</button>")

    def test_switching_back_to_english_also_persists(self):
        self.client.force_login(self.user)
        self.client.post(reverse("set_language"), {"language": "tr", "next": "/"})
        self.client.post(reverse("set_language"), {"language": "en", "next": "/"})

        response = self.client.get(reverse("home"), follow=True)

        self.assertContains(response, "My outcomes")


class TermTranslationTests(TestCase):
    def test_season_is_translated(self):
        term = Term(year=2026, season=Term.Season.FALL)

        with translation.override("en"):
            self.assertEqual(str(term), "2026 Fall")
        with translation.override("tr"):
            self.assertEqual(str(term), "2026 Güz")


class NumberFormatTests(TestCase):
    """The department's own numbers follow MÜDEK's Turkish convention too (#49)."""

    @classmethod
    def setUpTestData(cls):
        cls.term = Term.objects.create(year=2026, season=Term.Season.FALL)
        cls.course = Course.objects.create(code="CSE311", name="Software Engineering", ects=6)
        cls.offering = CourseOffering.objects.create(course=cls.course, term=cls.term)
        po1 = ProgramOutcome.objects.create(code="PO1")
        component = POComponent.objects.create(program_outcome=po1, code="a")
        lo1 = LearningOutcome.objects.create(offering=cls.offering, code="LO1")
        LOPOWeight.objects.create(learning_outcome=lo1, component=component, weight=1)

        midterm = Assessment.objects.create(offering=cls.offering, name="Midterm", max_score=D("100"))
        final = Assessment.objects.create(offering=cls.offering, name="Final", max_score=D("100"))
        AssessmentLOWeight.objects.create(assessment=midterm, learning_outcome=lo1, weight=D("1"))
        AssessmentLOWeight.objects.create(assessment=final, learning_outcome=lo1, weight=D("1"))

        cls.student = get_user_model().objects.create_user(username="elif")
        cls.student.groups.add(Group.objects.get_or_create(name=STUDENT)[0])
        enrollment = Enrollment.objects.create(offering=cls.offering, student=cls.student)
        # Same score on both: two assessments clear the thin-evidence bar
        # (#42) without needing a weighted-mean calculation to predict.
        Grade.objects.create(enrollment=enrollment, assessment=midterm, score=D("75.5"), term=cls.term)
        Grade.objects.create(enrollment=enrollment, assessment=final, score=D("75.5"), term=cls.term)

        cls.head = get_user_model().objects.create_user(username="head")
        cls.head.groups.add(Group.objects.get_or_create(name=INSTRUCTOR)[0])
        cls.offering.instructors.add(cls.head)
        refresh_materialized_views()

    def test_course_report_score_uses_a_comma_in_turkish(self):
        self.client.force_login(self.head)

        response = self.client.get(
            reverse("course_report", args=[self.offering.pk]), HTTP_ACCEPT_LANGUAGE="tr",
        )

        self.assertContains(response, "75,5")
        self.assertNotContains(response, "75.5")

    def test_course_report_score_uses_a_dot_in_english(self):
        self.client.force_login(self.head)

        response = self.client.get(reverse("course_report", args=[self.offering.pk]))

        self.assertContains(response, "75.5")
