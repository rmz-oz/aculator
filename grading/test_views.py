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
from .services import scores_with_evidence_by_enrollment

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

    def test_po_counts_one_assessment_reaching_it_through_two_los(self):
        lo2 = LearningOutcome.objects.create(offering=self.offering, code="LO2")
        AssessmentLOWeight.objects.create(
            assessment=self.midterm, learning_outcome=lo2, weight=D(1)
        )
        component = POComponent.objects.get(program_outcome=self.po1, code="a")
        LOPOWeight.objects.create(learning_outcome=lo2, component=component, weight=1)

        _, _, lo_counts, po_counts = scores_with_evidence_by_enrollment(
            [self.graded_enrollment]
        )[self.graded_enrollment.pk]

        self.assertEqual(lo_counts, {self.lo1.pk: 1, lo2.pk: 1})
        self.assertEqual(po_counts, {"PO1": 1})
    def setUp(self):
        self.client.force_login(self.head)


    def test_renders_scores_and_class_average(self):
        final = Assessment.objects.create(offering=self.offering, name="Final", max_score=D(100))
        AssessmentLOWeight.objects.create(
            assessment=final, learning_outcome=self.lo1, weight=D(1)
        )
        Grade.objects.create(
            enrollment=self.graded_enrollment, assessment=final, score=D(80)
        )

        response = self.client.get(reverse("course_report", args=[self.offering.pk]))

        self.assertContains(
            response,
            """
            <tr>
                <th scope="row">Elif Demir</th>
                <td>85.0</td>
                <td class="po-col">85.0</td>
            </tr>
            """,
            html=True,
        )
        self.assertEqual(response.context["lo_class_avg"], [D("85.0")])
        self.assertEqual(response.context["po_class_avg"], [D("85.0")])

    def test_report_distinguishes_low_evidence_from_no_evidence(self):
        response = self.client.get(reverse("course_report", args=[self.offering.pk]))

        self.assertContains(
            response,
            """
            <tr>
                <th scope="row">Elif Demir</th>
                <td><span class="low-evidence">Not enough evidence</span></td>
                <td class="po-col"><span class="low-evidence">Not enough evidence</span></td>
            </tr>
            """,
            html=True,
        )
        self.assertContains(
            response,
            """
            <tr>
                <th scope="row">can</th>
                <td><span title="No evidence">—</span></td>
                <td class="po-col"><span title="No evidence">—</span></td>
            </tr>
            """,
            html=True,
        )


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
