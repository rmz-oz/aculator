from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from .access import HEAD, INSTRUCTOR, STUDENT
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


class CourseReportViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.term = Term.objects.create(year=2026, season=Term.Season.FALL)
        cls.course = Course.objects.create(code="CSE311", name="Software Engineering", ects=6)
        cls.offering = CourseOffering.objects.create(course=cls.course, term=cls.term)
        cls.po1 = ProgramOutcome.objects.create(code="PO1")
        cls.lo1 = LearningOutcome.objects.create(offering=cls.offering, code="LO1")
        component = POComponent.objects.create(program_outcome=cls.po1, code="a")
        LOPOWeight.objects.create(learning_outcome=cls.lo1, component=component, weight=1)

        cls.midterm = Assessment.objects.create(offering=cls.offering, name="Midterm", max_score=D("100"))
        AssessmentLOWeight.objects.create(assessment=cls.midterm, learning_outcome=cls.lo1, weight=D("1"))

        cls.graded = get_user_model().objects.create_user(
            username="elif", first_name="Elif", last_name="Demir",
        )
        cls.graded_enrollment = Enrollment.objects.create(offering=cls.offering, student=cls.graded)
        Grade.objects.create(enrollment=cls.graded_enrollment, assessment=cls.midterm, score=D("90"))

        cls.ungraded = get_user_model().objects.create_user(username="can")
        Enrollment.objects.create(offering=cls.offering, student=cls.ungraded)

        users = get_user_model().objects
        cls.head = users.create_user(username="head")
        cls.head.groups.add(Group.objects.get(name=HEAD))
        cls.teacher = users.create_user(username="teacher")
        cls.teacher.groups.add(Group.objects.get(name=INSTRUCTOR))
        cls.offering.instructors.add(cls.teacher)
        cls.other_teacher = users.create_user(username="other-teacher")
        cls.other_teacher.groups.add(Group.objects.get(name=INSTRUCTOR))
        cls.graded.groups.add(Group.objects.get(name=STUDENT))

    def setUp(self):
        self.client.force_login(self.head)

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

        # session, user, role, then offering, LOs, enrollments, grades, LO weights, PO weights
        with self.assertNumQueries(9):
            self.client.get(reverse("course_report", args=[self.offering.pk]))

    def test_only_head_and_own_instructor_can_open_the_report(self):
        url = reverse("course_report", args=[self.offering.pk])
        cases = [
            (None, 404),
            (self.graded, 404),  # a student, even one in this course
            (self.other_teacher, 404),
            (self.teacher, 200),
            (self.head, 200),
        ]
        for user, status in cases:
            with self.subTest(user=user):
                self.client.logout()
                if user:
                    self.client.force_login(user)
                self.assertEqual(self.client.get(url).status_code, status)
