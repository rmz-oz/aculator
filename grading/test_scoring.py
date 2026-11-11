from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

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
from .services import (
    course_po_scores,
    display,
    lo_scores,
    offering_po_scores,
    student_po_scores,
    weighted_mean,
)

D = Decimal


class CalculationUtilityTests(SimpleTestCase):
    def test_weighted_mean(self):
        result = weighted_mean([
            (D("90"), D("0.6")),
            (D("80"), D("0.4")),
        ])

        self.assertEqual(result, D("86"))

    def test_empty_weighted_mean(self):
        self.assertIsNone(weighted_mean([]))

    def test_zero_total_weight(self):
        self.assertIsNone(
            weighted_mean([(D("90"), D("0"))])
        )

    def test_display_rounds_half_up(self):
        self.assertEqual(display(D("84.95")), D("85.0"))
        self.assertEqual(
            display(D("84.955"), places="0.01"),
            D("84.96"),
        )

    def test_display_preserves_none_and_zero(self):
        self.assertIsNone(display(None))
        self.assertEqual(display(D("0")), D("0.0"))


class ElifExampleTests(TestCase):
    """Worked example from the project guidelines, page 6."""

    @classmethod
    def setUpTestData(cls):
        cls.elif_ = get_user_model().objects.create_user(
            username="elif",
        )
        cls.term = Term.objects.create(
            year=2026,
            season=Term.Season.FALL,
        )
        cls.po1 = ProgramOutcome.objects.create(code="PO1")
        cls.po2 = ProgramOutcome.objects.create(code="PO2")

        cls.component1 = POComponent.objects.create(
            program_outcome=cls.po1,
            code="a",
        )
        cls.component2 = POComponent.objects.create(
            program_outcome=cls.po2,
            code="a",
        )

        cls.course = Course.objects.create(
            code="CSE311",
            name="Software Engineering",
            ects=6,
        )
        cls.offering = CourseOffering.objects.create(
            course=cls.course,
            term=cls.term,
        )
        cls.enrollment = Enrollment.objects.create(
            offering=cls.offering,
            student=cls.elif_,
        )

        cls.midterm = Assessment.objects.create(
            offering=cls.offering,
            name="Midterm",
            max_score=D("100"),
        )
        cls.project = Assessment.objects.create(
            offering=cls.offering,
            name="Project",
            max_score=D("100"),
        )

        Grade.objects.create(
            enrollment=cls.enrollment,
            assessment=cls.midterm,
            score=D("90"),
        )
        Grade.objects.create(
            enrollment=cls.enrollment,
            assessment=cls.project,
            score=D("80"),
        )

        cls.lo1 = LearningOutcome.objects.create(
            offering=cls.offering,
            code="LO1",
        )
        cls.lo2 = LearningOutcome.objects.create(
            offering=cls.offering,
            code="LO2",
        )

        for assessment, lo, weight in (
            (cls.midterm, cls.lo1, "0.6"),
            (cls.project, cls.lo1, "0.4"),
            (cls.midterm, cls.lo2, "0.4"),
            (cls.project, cls.lo2, "1.0"),
        ):
            AssessmentLOWeight.objects.create(
                assessment=assessment,
                learning_outcome=lo,
                weight=D(weight),
            )

        # Levels 2:1 preserve the guidelines' weight ratio 1.0:0.5.
        LOPOWeight.objects.create(
            learning_outcome=cls.lo1,
            component=cls.component1,
            weight=2,
        )
        LOPOWeight.objects.create(
            learning_outcome=cls.lo2,
            component=cls.component1,
            weight=1,
        )
        LOPOWeight.objects.create(
            learning_outcome=cls.lo2,
            component=cls.component2,
            weight=1,
        )

    def assert_decimal_close(self, actual, expected):
        self.assertIsInstance(actual, Decimal)
        self.assertLess(
            abs(actual - expected),
            D("0.00000000000000000001"),
        )

    def expected_lo2(self):
        return (
            D("90") * D("0.4") + D("80") * D("1.0")
        ) / D("1.4")

    def expected_po1(self):
        return (
            D("86") * D("2") + self.expected_lo2()
        ) / D("3")

    def test_lo_scores(self):
        scores = lo_scores(self.enrollment)

        self.assertEqual(scores[self.lo1.pk], D("86"))
        self.assert_decimal_close(
            scores[self.lo2.pk],
            self.expected_lo2(),
        )
        self.assertEqual(
            display(scores[self.lo2.pk]),
            D("82.9"),
        )

    def test_po1_is_85_not_84(self):
        scores = course_po_scores(self.enrollment)

        self.assertEqual(display(scores["PO1"]), D("85.0"))

    def test_po_scores_preserve_precision(self):
        scores = course_po_scores(self.enrollment)

        self.assert_decimal_close(
            scores["PO1"],
            self.expected_po1(),
        )
        self.assert_decimal_close(
            scores["PO2"],
            self.expected_lo2(),
        )
        self.assertEqual(display(scores["PO2"]), D("82.9"))

    def test_student_level_weights_courses_by_ects(self):
        course = Course.objects.create(
            code="MAT241",
            name="Math",
            ects=3,
        )
        offering = CourseOffering.objects.create(
            course=course,
            term=self.term,
        )
        enrollment = Enrollment.objects.create(
            offering=offering,
            student=self.elif_,
        )
        assessment = Assessment.objects.create(
            offering=offering,
            name="Final",
            max_score=D("100"),
        )
        Grade.objects.create(
            enrollment=enrollment,
            assessment=assessment,
            score=D("70"),
        )
        lo = LearningOutcome.objects.create(
            offering=offering,
            code="LO1",
        )
        AssessmentLOWeight.objects.create(
            assessment=assessment,
            learning_outcome=lo,
            weight=D("1"),
        )
        LOPOWeight.objects.create(
            learning_outcome=lo,
            component=self.component1,
            weight=1,
        )

        scores = student_po_scores(self.elif_)
        expected = (
            self.expected_po1() * D("6") + D("70") * D("3")
        ) / D("9")

        self.assert_decimal_close(scores["PO1"], expected)
        self.assertEqual(display(scores["PO1"]), D("80.0"))

        # A course without a PO2 contribution must not dilute PO2.
        self.assert_decimal_close(
            scores["PO2"],
            self.expected_lo2(),
        )

    def test_course_level_averages_students(self):
        ayse = get_user_model().objects.create_user(
            username="ayse",
        )
        enrollment = Enrollment.objects.create(
            offering=self.offering,
            student=ayse,
        )

        for assessment in (self.midterm, self.project):
            Grade.objects.create(
                enrollment=enrollment,
                assessment=assessment,
                score=D("100"),
            )

        scores = offering_po_scores(self.offering)

        self.assert_decimal_close(
            scores["PO1"],
            (self.expected_po1() + D("100")) / D("2"),
        )
        self.assert_decimal_close(
            scores["PO2"],
            (self.expected_lo2() + D("100")) / D("2"),
        )
        self.assertEqual(display(scores["PO1"]), D("92.5"))
        self.assertEqual(display(scores["PO2"]), D("91.4"))

    def test_scores_are_normalized_by_max_score(self):
        self.midterm.max_score = D("50")
        self.midterm.save(update_fields=["max_score"])

        Grade.objects.filter(
            enrollment=self.enrollment,
            assessment=self.midterm,
        ).update(score=D("40"))

        scores = lo_scores(self.enrollment)

        # Midterm: 40/50 = 80%; project: 80/100 = 80%.
        self.assertEqual(scores[self.lo1.pk], D("80"))
        self.assertEqual(scores[self.lo2.pk], D("80"))

    def test_missing_grade_uses_available_weights(self):
        Grade.objects.filter(
            enrollment=self.enrollment,
            assessment=self.project,
        ).delete()

        scores = lo_scores(self.enrollment)

        self.assertEqual(scores[self.lo1.pk], D("90"))
        self.assertEqual(scores[self.lo2.pk], D("90"))

    def test_zero_max_score_is_excluded(self):
        self.midterm.max_score = D("0")
        self.midterm.save(update_fields=["max_score"])

        scores = lo_scores(self.enrollment)

        self.assertEqual(scores[self.lo1.pk], D("80"))
        self.assertEqual(scores[self.lo2.pk], D("80"))

    def test_zero_lo_weights_produce_no_scores(self):
        AssessmentLOWeight.objects.filter(
            learning_outcome__offering=self.offering,
        ).update(weight=D("0"))

        self.assertEqual(lo_scores(self.enrollment), {})
        self.assertEqual(course_po_scores(self.enrollment), {})

    def test_actual_zero_grades_are_preserved(self):
        Grade.objects.filter(
            enrollment=self.enrollment,
        ).update(score=D("0"))

        self.assertEqual(
            course_po_scores(self.enrollment),
            {"PO1": D("0"), "PO2": D("0")},
        )

    def test_no_grades_produce_no_scores(self):
        Grade.objects.filter(
            enrollment=self.enrollment,
        ).delete()

        self.assertEqual(lo_scores(self.enrollment), {})
        self.assertEqual(course_po_scores(self.enrollment), {})
        self.assertEqual(student_po_scores(self.elif_), {})
        self.assertEqual(offering_po_scores(self.offering), {})

    def test_ungraded_student_does_not_dilute_course_scores(self):
        student = get_user_model().objects.create_user(
            username="ungraded",
        )
        Enrollment.objects.create(
            offering=self.offering,
            student=student,
        )

        scores = offering_po_scores(self.offering)

        self.assert_decimal_close(
            scores["PO1"],
            self.expected_po1(),
        )

    def test_zero_ects_produce_no_student_scores(self):
        self.course.ects = 0
        self.course.save(update_fields=["ects"])

        self.assertEqual(student_po_scores(self.elif_), {})

    def test_student_without_enrollments_has_no_scores(self):
        student = get_user_model().objects.create_user(
            username="no-enrollments",
        )

        self.assertEqual(student_po_scores(student), {})

    def test_student_scores_query_count(self):
        # Enrollments, grades, assessment weights, component weights.
        with self.assertNumQueries(4):
            student_po_scores(self.elif_)

    def test_offering_scores_query_count(self):
        for n in range(5):
            student = get_user_model().objects.create_user(username=f"s{n}")
            Enrollment.objects.create(
                offering=self.offering,
                student=student,
            )

        with self.assertNumQueries(4):
            offering_po_scores(self.offering)