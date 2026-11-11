from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import (
    Assessment,
    AssessmentLOWeight,
    Course,
    CourseOffering,
    Enrollment,
    Grade,
    LearningOutcome,
    LOPOWeight,
    ProgramOutcome,
    Term,
)

D = Decimal


class CourseReportViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.term = Term.objects.create(year=2026, season=Term.Season.FALL)
        cls.course = Course.objects.create(code="CSE311", name="Software Engineering", ects=6)
        cls.offering = CourseOffering.objects.create(course=cls.course, term=cls.term)
        cls.po1 = ProgramOutcome.objects.create(code="PO1")
        cls.lo1 = LearningOutcome.objects.create(offering=cls.offering, code="LO1")
        LOPOWeight.objects.create(learning_outcome=cls.lo1, program_outcome=cls.po1, weight=1)

        cls.midterm = Assessment.objects.create(offering=cls.offering, name="Midterm", max_score=D("100"))
        AssessmentLOWeight.objects.create(assessment=cls.midterm, learning_outcome=cls.lo1, weight=D("1"))

        cls.graded = get_user_model().objects.create_user(
            username="elif", first_name="Elif", last_name="Demir",
        )
        cls.graded_enrollment = Enrollment.objects.create(offering=cls.offering, student=cls.graded)
        Grade.objects.create(enrollment=cls.graded_enrollment, assessment=cls.midterm, score=D("90"))

        cls.ungraded = get_user_model().objects.create_user(username="can")
        Enrollment.objects.create(offering=cls.offering, student=cls.ungraded)

    def test_renders_scores_and_class_average(self):
        response = self.client.get(reverse("course_report", args=[self.offering.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Elif Demir")
        self.assertContains(response, "LO1")
        self.assertContains(response, "PO1")
        self.assertContains(response, "90.0")

    def test_ungraded_student_shows_not_enough_evidence(self):
        response = self.client.get(reverse("course_report", args=[self.offering.pk]))

        self.assertContains(response, "can")
        self.assertContains(response, "Not enough evidence")

    def test_unknown_offering_is_404(self):
        response = self.client.get(reverse("course_report", args=[self.offering.pk + 999]))

        self.assertEqual(response.status_code, 404)

    def test_offering_with_no_enrollments(self):
        empty_offering = CourseOffering.objects.create(
            course=Course.objects.create(code="CSE999", name="Empty", ects=3),
            term=self.term,
        )

        response = self.client.get(reverse("course_report", args=[empty_offering.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No students enrolled yet")

    def test_query_count_does_not_grow_per_student(self):
        for i in range(10):
            student = get_user_model().objects.create_user(username=f"extra{i}")
            Enrollment.objects.create(offering=self.offering, student=student)

        with self.assertNumQueries(6):  # offering, LOs, enrollments, grades, LO weights, PO weights
            self.client.get(reverse("course_report", args=[self.offering.pk]))
