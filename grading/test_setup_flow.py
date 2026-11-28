"""Setting up a course without the admin: makeups, assessment weights, and saying what a makeup replaced."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from .access import INSTRUCTOR, STUDENT
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


class SetupFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.teacher = users.create_user("teacher")
        cls.teacher.groups.add(Group.objects.get_or_create(name=INSTRUCTOR)[0])
        cls.other = users.create_user("other")
        cls.other.groups.add(Group.objects.get_or_create(name=INSTRUCTOR)[0])
        cls.student = users.create_user("student", first_name="Ada", last_name="Kaya")
        cls.student.groups.add(Group.objects.get_or_create(name=STUDENT)[0])
        term = Term.objects.create(year=2026, season=Term.Season.SPRING)
        course = Course.objects.create(code="CSE202", name="Data Structures", ects=6)
        cls.offering = CourseOffering.objects.create(course=course, term=term)
        cls.offering.instructors.add(cls.teacher)
        cls.lo1 = LearningOutcome.objects.create(offering=cls.offering, code="LO1")
        cls.lo2 = LearningOutcome.objects.create(offering=cls.offering, code="LO2")
        po = ProgramOutcome.objects.create(code="PO1")
        component = POComponent.objects.create(program_outcome=po, code="a")
        LOPOWeight.objects.create(learning_outcome=cls.lo1, component=component, weight=3)
        cls.midterm = Assessment.objects.create(offering=cls.offering, name="Midterm")
        cls.final = Assessment.objects.create(offering=cls.offering, name="Final")
        AssessmentLOWeight.objects.create(assessment=cls.final, learning_outcome=cls.lo1, weight=D("0.6"))
        AssessmentLOWeight.objects.create(assessment=cls.midterm, learning_outcome=cls.lo1, weight=D("0.4"))
        cls.enrollment = Enrollment.objects.create(offering=cls.offering, student=cls.student)

    # Makeups (#105)

    def test_report_offers_a_makeup_for_the_final_only(self):
        self.client.force_login(self.teacher)
        page = self.client.get(reverse("course_report", args=[self.offering.pk])).content.decode()
        self.assertIn(reverse("add_makeup", args=[self.final.pk]), page)
        self.assertNotIn(reverse("add_makeup", args=[self.midterm.pk]), page)

    def test_adding_a_makeup_copies_the_final(self):
        self.client.force_login(self.teacher)
        response = self.client.post(reverse("add_makeup", args=[self.final.pk]))
        makeup = Assessment.objects.get(replaces=self.final)
        self.assertRedirects(response, reverse("grade_import", args=[makeup.pk]), fetch_redirect_response=False)
        self.assertEqual((makeup.name, makeup.max_score), ("Makeup", self.final.max_score))
        self.assertEqual(list(makeup.lo_weights.values_list("learning_outcome_id", "weight")), [(self.lo1.pk, D("0.6"))])
        # A second click goes to the same makeup; the report stops offering it.
        self.client.post(reverse("add_makeup", args=[self.final.pk]))
        self.assertEqual(Assessment.objects.filter(replaces=self.final).count(), 1)
        page = self.client.get(reverse("course_report", args=[self.offering.pk])).content.decode()
        self.assertNotIn(reverse("add_makeup", args=[self.final.pk]), page)
        page = self.client.get(reverse("grade_import", args=[makeup.pk])).content.decode()
        self.assertIn("A grade here replaces the student's Final", page)

    def test_only_the_instructor_adds_a_makeup_and_only_by_post(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(reverse("add_makeup", args=[self.final.pk])).status_code, 404)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("add_makeup", args=[self.final.pk])).status_code, 405)
        self.assertFalse(Assessment.objects.filter(replaces=self.final).exists())

    def test_po_page_says_what_the_makeup_replaced(self):
        makeup = Assessment.objects.create(offering=self.offering, name="Makeup", replaces=self.final)
        AssessmentLOWeight.objects.create(assessment=makeup, learning_outcome=self.lo1, weight=D("0.6"))
        Grade.objects.create(enrollment=self.enrollment, assessment=self.midterm, score=D(50))
        Grade.objects.create(enrollment=self.enrollment, assessment=self.final, score=D(38))
        Grade.objects.create(enrollment=self.enrollment, assessment=makeup, score=D(61))
        self.client.force_login(self.student)
        page = self.client.get(reverse("po_detail", args=[self.student.pk, "PO1"])).content.decode()
        self.assertIn("CSE202 Final 38.0 is not counted: the Makeup (61.0) replaces it", page)

    # Assessment weights

    def test_weights_grid_shows_and_saves(self):
        self.client.force_login(self.teacher)
        url = reverse("assessment_weights", args=[self.offering.pk])
        page = self.client.get(url)
        self.assertContains(page, "No assessment measures LO2 yet")
        data = {
            "fingerprint": page.context["fingerprint"],
            f"w_{self.final.pk}_{self.lo1.pk}": "70",
            f"w_{self.midterm.pk}_{self.lo1.pk}": "",  # removed
            f"w_{self.midterm.pk}_{self.lo2.pk}": "33,5",  # decimal comma
        }
        response = self.client.post(url, data)
        self.assertContains(response, "Weights saved.")
        self.assertEqual(
            sorted(AssessmentLOWeight.objects.values_list("assessment__name", "learning_outcome__code", "weight")),
            [("Final", "LO1", D("0.7000")), ("Midterm", "LO2", D("0.3350"))],
        )
        self.assertNotContains(response, "No assessment measures")

    def test_weights_out_of_range_or_stale_save_nothing(self):
        self.client.force_login(self.teacher)
        url = reverse("assessment_weights", args=[self.offering.pk])
        fingerprint = self.client.get(url).context["fingerprint"]
        response = self.client.post(url, {"fingerprint": fingerprint, f"w_{self.final.pk}_{self.lo1.pk}": "150"})
        self.assertContains(response, "enter a weight from 0 to 100", status_code=400)
        AssessmentLOWeight.objects.filter(assessment=self.midterm).update(weight=D("0.5"))
        response = self.client.post(url, {"fingerprint": fingerprint, f"w_{self.final.pk}_{self.lo1.pk}": "20"})
        self.assertContains(response, "The weights changed", status_code=400)
        self.assertEqual(AssessmentLOWeight.objects.get(assessment=self.final).weight, D("0.6"))

    def test_weights_are_for_the_instructor_only(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("assessment_weights", args=[self.offering.pk])).status_code, 404)
