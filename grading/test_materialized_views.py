from decimal import Decimal
from unittest import mock

from django.db import connection, transaction
from django.test import TestCase

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
)
from .services import course_po_scores, lo_scores, student_po_scores
from .test_scoring import ElifExampleTests

TOL = Decimal("1e-20")


def rows(sql):
    with connection.cursor() as cursor:
        cursor.execute(sql)
        return cursor.fetchall()


class MaterializedViewTests(TestCase):
    """The views must give the same numbers as the calculation service."""

    @classmethod
    def setUpTestData(cls):
        ElifExampleTests.setUpTestData.__func__(cls)
        # A second course with half the ECTS, for the cross course view.
        course = Course.objects.create(code="MAT241", name="Math", ects=3)
        offering = CourseOffering.objects.create(course=course, term=cls.term)
        enrollment = Enrollment.objects.create(offering=offering, student=cls.elif_)
        final = Assessment.objects.create(offering=offering, name="Final", max_score=Decimal(50))
        Grade.objects.create(enrollment=enrollment, assessment=final, score=Decimal(35))
        lo = LearningOutcome.objects.create(offering=offering, code="LO1")
        AssessmentLOWeight.objects.create(assessment=final, learning_outcome=lo, weight=Decimal(1))
        LOPOWeight.objects.create(
            learning_outcome=lo,
            component=cls.component1,
            weight=3,
        )

    def setUp(self):
        # Grades made in setUpTestData queued refreshes on the class transaction,
        # which a TestCase never commits. Start each test without them.
        connection.run_on_commit.clear()

    def assertClose(self, a, b):
        self.assertLess(abs(a - b), TOL, f"{a} != {b}")

    def test_views_match_the_service(self):
        refresh_materialized_views()
        for enrollment in Enrollment.objects.all():
            expected = lo_scores(enrollment)
            got = dict(rows(
                "select learning_outcome_id, score from student_lo_scores "
                f"where student_id = {enrollment.student_id} and offering_id = {enrollment.offering_id}"
            ))
            self.assertEqual(got.keys(), expected.keys())
            for key in expected:
                self.assertClose(got[key], expected[key])

            expected = course_po_scores(enrollment)
            got = dict(rows(
                "select p.code, v.score from course_po_scores v join grading_programoutcome p on p.id = v.program_outcome_id "
                f"where v.student_id = {enrollment.student_id} and v.offering_id = {enrollment.offering_id}"
            ))
            self.assertEqual(got.keys(), expected.keys())
            for key in expected:
                self.assertClose(got[key], expected[key])

    def test_cross_course_view_weights_by_ects(self):
        refresh_materialized_views()
        expected = student_po_scores(self.elif_)
        got = dict(rows(
            "select p.code, v.score from cross_course_po_scores v join grading_programoutcome p on p.id = v.program_outcome_id "
            f"where v.student_id = {self.elif_.pk}"
        ))
        self.assertEqual(got.keys(), expected.keys())
        for key in expected:
            self.assertClose(got[key], expected[key])
        # 6 ECTS at 84.952 and 3 ECTS at 70 give 79.968, a plain average would give 77.476.
        self.assertEqual(got["PO1"].quantize(Decimal("0.1")), Decimal("80.0"))

    def test_zero_max_score_and_zero_weights_leave_no_null_rows(self):
        self.midterm.max_score = Decimal(0)
        self.midterm.save(update_fields=["max_score"])
        AssessmentLOWeight.objects.filter(learning_outcome=self.lo2).update(weight=Decimal(0))
        refresh_materialized_views()
        for view in ("student_lo_scores", "course_po_scores", "cross_course_po_scores"):
            self.assertEqual(rows(f"select count(*) from {view} where score is null")[0][0], 0, view)
        self.test_views_match_the_service()

    def test_grade_change_refreshes_once_after_commit(self):
        with (
            mock.patch("grading.signals.refresh_materialized_views") as refresh,
            self.captureOnCommitCallbacks(execute=True),
            transaction.atomic(),
        ):
            for grade in Grade.objects.all():
                grade.score = grade.score - 1
                grade.save()
        # Three grades changed, one refresh.
        self.assertEqual(refresh.call_count, 1)

    def test_rolled_back_change_does_not_refresh(self):
        with mock.patch("grading.signals.refresh_materialized_views") as refresh:
            with self.captureOnCommitCallbacks(execute=True):
                try:
                    with transaction.atomic():
                        Grade.objects.first().delete()
                        raise RuntimeError
                except RuntimeError:
                    pass
            self.assertEqual(refresh.call_count, 0)

    def test_saved_grade_reaches_the_view(self):
        refresh_materialized_views()
        grade = Grade.objects.get(enrollment=self.enrollment, assessment=self.project)
        with self.captureOnCommitCallbacks(execute=True):
            grade.score = Decimal(100)
            grade.save()
        got = dict(rows(
            "select learning_outcome_id, score from student_lo_scores "
            f"where student_id = {self.elif_.pk} and offering_id = {self.offering.pk}"
        ))
        # LO1: 0.6 * 90 + 0.4 * 100 = 94
        self.assertEqual(got[self.lo1.pk], Decimal(94))
