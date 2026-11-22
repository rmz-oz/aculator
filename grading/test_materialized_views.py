import io
from decimal import Decimal
from unittest import mock

from django.core.management import call_command
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
    Term,
)
from .services import (
    course_po_scores,
    lo_scores,
    report_scores_from_views,
    scores_with_evidence_by_enrollment,
    student_po_scores,
)
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

    def test_catalog_ects_change_keeps_existing_po_scores(self):
        sql = (
            "SELECT score FROM cross_course_po_scores "
            f"WHERE student_id = {self.elif_.pk} "
            f"AND program_outcome_id = {self.po1.pk}"
        )
        refresh_materialized_views()
        score_before = student_po_scores(self.elif_)["PO1"]
        view_before = rows(sql)
        self.assertEqual(len(view_before), 1)

        self.course.ects = 12
        self.course.save(update_fields=["ects"])
        refresh_materialized_views()

        self.offering.refresh_from_db()
        self.assertEqual(self.offering.ects, 6)
        self.assertEqual(student_po_scores(self.elif_)["PO1"], score_before)
        self.assertEqual(rows(sql), view_before)

        next_term = Term.objects.create(
            year=self.term.year + 1,
            season=self.term.season,
        )
        new_offering = CourseOffering.objects.create(
            course=self.course,
            term=next_term,
        )
        self.assertEqual(new_offering.ects, 12)

        later_term = Term.objects.create(year=self.term.year + 2, season=self.term.season)
        set_by_head = CourseOffering.objects.create(course=self.course, term=later_term, ects=8)
        self.assertEqual(set_by_head.ects, 8)

    def test_absent_grade_matches_the_service(self):
        Grade.objects.filter(enrollment=self.enrollment, assessment=self.project).update(
            status=Grade.Status.ABSENT, score=Decimal(0),
        )
        self.test_views_match_the_service()
        got = dict(rows(
            "select learning_outcome_id, score from student_lo_scores "
            f"where student_id = {self.elif_.pk} and offering_id = {self.offering.pk}"
        ))
        self.assertEqual(got[self.lo1.pk], Decimal(54))

    def test_zero_weights_leave_no_null_rows(self):
        AssessmentLOWeight.objects.filter(learning_outcome=self.lo2).update(weight=Decimal(0))
        refresh_materialized_views()
        for view in ("student_lo_scores", "course_po_scores", "cross_course_po_scores"):
            self.assertEqual(rows(f"select count(*) from {view} where score is null")[0][0], 0, view)
        self.test_views_match_the_service()

    def test_grade_change_refreshes_once_after_commit(self):
        with (
            mock.patch("grading.signals.refresh_scores") as refresh,
            self.captureOnCommitCallbacks(execute=True),
            transaction.atomic(),
        ):
            for grade in Grade.objects.all():
                grade.score = grade.score - 1
                grade.save()
        # Every grade changed, one refresh, for exactly their offerings.
        self.assertEqual(refresh.call_count, 1)
        offerings = set(Grade.objects.values_list("assessment__offering_id", flat=True))
        self.assertEqual(set(refresh.call_args.args[0]), offerings)

    def test_rolled_back_change_does_not_refresh(self):
        with mock.patch("grading.signals.refresh_scores") as refresh:
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

    def test_weight_change_reaches_the_view(self):
        refresh_materialized_views()
        weight = AssessmentLOWeight.objects.get(assessment=self.midterm, learning_outcome=self.lo1)
        with self.captureOnCommitCallbacks(execute=True):
            weight.weight = Decimal(1)
            weight.save()
        got = dict(rows(
            "select learning_outcome_id, score from student_lo_scores "
            f"where student_id = {self.elif_.pk} and offering_id = {self.offering.pk}"
        ))
        # LO1 now 1 * 90 + 0.4 * 80, over 1.4
        self.assertClose(got[self.lo1.pk], (Decimal(90) + Decimal("0.4") * 80) / Decimal("1.4"))

    def test_moving_an_offering_to_another_course_reaches_the_view(self):
        # Only the offering changes inside the block: its course now has 6 ECTS, not 3.
        math_two = Course.objects.create(code="MAT242", name="Math II", ects=6)
        connection.run_on_commit.clear()
        refresh_materialized_views()
        math = CourseOffering.objects.get(course__code="MAT241")
        with self.captureOnCommitCallbacks(execute=True):
            math.course = math_two
            math.save()
        got = dict(rows(
            "select program_outcome_id, score from cross_course_po_scores "
            f"where student_id = {self.elif_.pk}"
        ))
        want = student_po_scores(self.elif_)
        self.assertClose(got[self.po1.pk], want["PO1"])


class CourseReportFromViewsTests(TestCase):
    """The course report reads the views (#79); it must show what the service computes."""

    @classmethod
    def setUpTestData(cls):
        call_command("fake_data", students=30, years=1, stdout=io.StringIO())
        # The fake data has neither of these; the views treat both specially.
        grade = Grade.objects.order_by("pk").first()
        grade.status, grade.score = Grade.Status.ABSENT, Decimal(0)
        grade.save()
        AssessmentLOWeight.objects.filter(pk=AssessmentLOWeight.objects.order_by("pk").first().pk).update(
            weight=Decimal(0)
        )

    def test_every_offering_matches_the_service(self):
        refresh_materialized_views()
        offerings = CourseOffering.objects.filter(enrollments__isnull=False).distinct()
        self.assertGreater(offerings.count(), 1)
        for offering in offerings:
            enrollments = list(offering.enrollments.all())
            expected = scores_with_evidence_by_enrollment(enrollments)
            got = report_scores_from_views(enrollments)
            self.assertEqual(got.keys(), expected.keys())
            for pk in expected:
                for want, have in zip(expected[pk], got[pk]):
                    self.assertEqual(have.keys(), want.keys(), f"offering {offering.pk}, enrollment {pk}")
                    for key in want:
                        self.assertLess(abs(have[key] - want[key]), TOL, f"offering {offering.pk}, {key}")

    def test_no_enrollments(self):
        self.assertEqual(report_scores_from_views([]), {})
