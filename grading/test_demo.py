from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from . import access
from .demo import DEMO_HEAD, DEMO_INSTRUCTOR, DEMO_STUDENT, ensure_demo_accounts
from .models import CourseOffering, Grade


def quiet(*args, **kwargs):
    call_command(*args, stdout=StringIO(), **kwargs)


class DemoAccountsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        quiet("demo_data", "--clean", students=5)

    def test_one_account_per_role(self):
        User = get_user_model()
        self.assertEqual(access.role_of(User.objects.get(username=DEMO_STUDENT)), access.STUDENT)
        self.assertEqual(access.role_of(User.objects.get(username=DEMO_INSTRUCTOR)), access.INSTRUCTOR)
        self.assertEqual(access.role_of(User.objects.get(username=DEMO_HEAD)), access.HEAD)

    def test_demo_accounts_have_no_password(self):
        for username in (DEMO_STUDENT, DEMO_INSTRUCTOR, DEMO_HEAD):
            self.assertFalse(get_user_model().objects.get(username=username).has_usable_password())

    def test_every_fake_student_is_a_student(self):
        students = get_user_model().objects.filter(username__startswith="fake_student_")
        self.assertEqual(students.count(), 5)
        self.assertTrue(all(access.role_of(s) == access.STUDENT for s in students))

    def test_instructor_teaches_offerings_with_students(self):
        instructor = get_user_model().objects.get(username=DEMO_INSTRUCTOR)
        offerings = CourseOffering.objects.filter(instructors=instructor)
        self.assertEqual(set(offerings.values_list("course__code", flat=True)), {"CSE203", "CSE301"})
        self.assertTrue(access.visible_enrollments(instructor).exists())

    def test_running_again_adds_nothing(self):
        grades = Grade.objects.count()
        users = get_user_model().objects.count()
        quiet("demo_data", "--if-empty")
        ensure_demo_accounts()
        self.assertEqual(Grade.objects.count(), grades)
        self.assertEqual(get_user_model().objects.count(), users)


class DemoSwitchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        quiet("demo_data", "--clean", students=5)

    def switch(self, role):
        return self.client.post(reverse("demo_switch", args=[role]))

    def test_off_by_default(self):
        self.assertEqual(self.switch("head").status_code, 404)
        self.assertNotContains(self.client.get(reverse("login")), "Demo, sign in as")

    @override_settings(DEMO=True)
    def test_login_page_offers_the_three_roles(self):
        page = self.client.get(reverse("login"))
        self.assertContains(page, "Demo, sign in as")
        for role in ("student", "instructor", "head"):
            self.assertContains(page, reverse("demo_switch", args=[role]))

    @override_settings(DEMO=True)
    def test_student_lands_on_their_profile(self):
        student = get_user_model().objects.get(username=DEMO_STUDENT)
        response = self.switch("student")
        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)
        self.assertRedirects(
            self.client.get(reverse("home")), reverse("student_profile", args=[student.pk])
        )

    @override_settings(DEMO=True)
    def test_switching_changes_the_role(self):
        self.switch("instructor")
        page = self.client.get(reverse("home"))
        self.assertContains(page, "Deniz Demo, instructor")
        self.assertContains(page, "CSE301")
        self.assertNotContains(page, "CSE101")

        self.switch("head")
        page = self.client.get(reverse("home"))
        self.assertContains(page, "Selin Demo, head of department")
        self.assertContains(page, "CSE101")

    @override_settings(DEMO=True)
    def test_get_and_unknown_roles_do_nothing(self):
        self.assertEqual(self.client.get(reverse("demo_switch", args=["head"])).status_code, 405)
        self.assertEqual(self.switch("admin").status_code, 404)
        self.assertNotIn("_auth_user_id", self.client.session)

    @override_settings(DEMO=True)
    def test_needs_csrf(self):
        client = self.client_class(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse("demo_switch", args=["head"])).status_code, 403)


class DemoScenarioTests(TestCase):
    """The realistic mistakes (#100) on a small department; positions come from the seed."""

    @classmethod
    def setUpTestData(cls):
        quiet("demo_data", students=60)

    def test_scenarios_are_in(self):
        from .demo_scenarios import UNMEASURED_PO
        from .models import LearningOutcome, LOPOWeight, Term

        self.assertFalse(LOPOWeight.objects.filter(component__program_outcome__code=UNMEASURED_PO).exists())
        current = CourseOffering.objects.filter(term__year=2026, term__season="fall")
        self.assertFalse(Grade.objects.filter(assessment__offering__in=current).exclude(assessment__name="Midterm").exists())
        self.assertTrue(Grade.objects.filter(status=Grade.Status.ABSENT).exists())
        self.assertTrue(Term.objects.filter(season="summer").exists())
        self.assertEqual(CourseOffering.objects.get(course__code="CSE491").enrollments.count(), 3)
        self.assertEqual(CourseOffering.objects.get(course__code="CSE101", term__year=2025, term__season="fall")
                         .enrollments.count(), 200)
        self.assertFalse(LearningOutcome.objects.filter(
            offering__course__code="CSE303", offering__term__year=2026, offering__term__season="spring").exists())

    def test_no_grade_above_its_maximum(self):
        from django.db.models import F

        self.assertFalse(Grade.objects.filter(score__gt=F("assessment__max_score")).exists())

    def test_loading_leaves_no_grade_history(self):
        # Otherwise the history shows each scenario mistake as an edit away from the right score.
        from .models import GradeChange

        self.assertFalse(GradeChange.objects.exists())

    def test_running_again_changes_nothing(self):
        grades = sorted(Grade.objects.values_list("pk", "score", "status"))
        quiet("demo_data")
        self.assertEqual(sorted(Grade.objects.values_list("pk", "score", "status")), grades)

    def test_every_page_opens_for_the_head(self):
        self.client.force_login(get_user_model().objects.get(username=DEMO_HEAD))
        for offering in CourseOffering.objects.all():
            self.assertEqual(self.client.get(reverse("course_report", args=[offering.pk])).status_code, 200, offering)
        for student in get_user_model().objects.filter(username__startswith="fake_student_")[::7]:
            self.assertEqual(self.client.get(reverse("student_profile", args=[student.pk])).status_code, 200, student)

    def test_offering_without_learning_outcomes_says_why(self):
        self.client.force_login(get_user_model().objects.get(username=DEMO_HEAD))
        offering = CourseOffering.objects.get(course__code="CSE303", term__year=2026, term__season="spring")
        self.assertContains(self.client.get(reverse("course_report", args=[offering.pk])),
                            "No learning outcomes are defined")
