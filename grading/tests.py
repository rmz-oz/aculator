from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

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


class GradingModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        student = get_user_model().objects.create_user(username="elif")
        course = Course.objects.create(
            code="CSE321",
            name="Software Engineering",
            ects=6,
        )
        fall = Term.objects.create(year=2026, season=Term.Season.FALL)
        spring = Term.objects.create(year=2027, season=Term.Season.SPRING)

        cls.offering = CourseOffering.objects.create(course=course, term=fall)
        cls.other_offering = CourseOffering.objects.create(
            course=course,
            term=spring,
        )
        cls.enrollment = Enrollment.objects.create(
            offering=cls.offering,
            student=student,
        )
        cls.assessment = Assessment.objects.create(
            offering=cls.offering,
            name="Midterm",
            max_score=Decimal("100.00"),
        )
        cls.other_assessment = Assessment.objects.create(
            offering=cls.other_offering,
            name="Midterm",
            max_score=Decimal("100.00"),
        )
        cls.lo = LearningOutcome.objects.create(
            offering=cls.offering,
            code="LO1",
        )
        cls.other_lo = LearningOutcome.objects.create(
            offering=cls.other_offering,
            code="LO1",
        )
        cls.po = ProgramOutcome.objects.create(code="PO1")

    def assert_database_rejects(self, model, **fields):
        # The savepoint keeps this TestCase's transaction usable after failure.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                model.objects.create(**fields)

    def test_grade_above_max_score_is_rejected(self):
        grade = Grade(
            enrollment=self.enrollment,
            assessment=self.assessment,
            score=Decimal("100.01"),
        )

        with self.assertRaises(ValidationError) as caught:
            grade.full_clean()

        self.assertEqual(
            caught.exception.message_dict["score"],
            ["Score must not exceed 100.00."],
        )

    def test_grade_from_another_offering_is_rejected(self):
        grade = Grade(
            enrollment=self.enrollment,
            assessment=self.other_assessment,
            score=Decimal("80.00"),
        )

        with self.assertRaisesMessage(
            ValidationError,
            "Enrollment and assessment must belong to the same offering.",
        ):
            grade.full_clean()

    def test_grade_accepts_zero_and_max_score(self):
        for score in (Decimal("0.00"), Decimal("100.00")):
            with self.subTest(score=score):
                grade = Grade(
                    enrollment=self.enrollment,
                    assessment=self.assessment,
                    score=score,
                )
                grade.full_clean()
                grade.save()
                grade.delete()

    def test_duplicate_grade_is_rejected(self):
        fields = {
            "enrollment": self.enrollment,
            "assessment": self.assessment,
            "score": Decimal("80.00"),
        }
        Grade.objects.create(**fields)

        with self.assertRaises(ValidationError):
            Grade(**fields).full_clean()

        self.assert_database_rejects(Grade, **fields)

    def test_negative_grade_is_rejected(self):
        fields = {
            "enrollment": self.enrollment,
            "assessment": self.assessment,
            "score": Decimal("-0.01"),
        }

        with self.assertRaises(ValidationError):
            Grade(**fields).full_clean()

        self.assert_database_rejects(Grade, **fields)

    def test_assessment_lo_weight_from_another_offering_is_rejected(self):
        weight = AssessmentLOWeight(
            assessment=self.assessment,
            learning_outcome=self.other_lo,
            weight=Decimal("0.5000"),
        )

        with self.assertRaisesMessage(
            ValidationError,
            "Assessment and learning outcome must belong to the same offering.",
        ):
            weight.full_clean()

    def test_assessment_lo_weight_outside_range_is_rejected(self):
        for value in (Decimal("-0.0001"), Decimal("1.0001")):
            with self.subTest(weight=value):
                fields = {
                    "assessment": self.assessment,
                    "learning_outcome": self.lo,
                    "weight": value,
                }

                with self.assertRaises(ValidationError):
                    AssessmentLOWeight(**fields).full_clean()

                self.assert_database_rejects(AssessmentLOWeight, **fields)

    def test_assessment_lo_weight_accepts_boundaries(self):
        for value in (Decimal("0.0000"), Decimal("1.0000")):
            with self.subTest(weight=value):
                weight = AssessmentLOWeight(
                    assessment=self.assessment,
                    learning_outcome=self.lo,
                    weight=value,
                )
                weight.full_clean()
                weight.save()
                weight.delete()

    def test_lo_po_weight_outside_range_is_rejected(self):
        for value in (0, 6):
            with self.subTest(weight=value):
                fields = {
                    "learning_outcome": self.lo,
                    "program_outcome": self.po,
                    "weight": value,
                }

                with self.assertRaises(ValidationError):
                    LOPOWeight(**fields).full_clean()

                self.assert_database_rejects(LOPOWeight, **fields)

    def test_lo_po_weight_accepts_all_five_levels(self):
        for value in range(1, 6):
            with self.subTest(weight=value):
                weight = LOPOWeight(
                    learning_outcome=self.lo,
                    program_outcome=self.po,
                    weight=value,
                )
                weight.full_clean()
                weight.save()
                weight.delete()

    def test_negative_assessment_max_score_is_rejected(self):
        fields = {
            "offering": self.offering,
            "name": "Invalid assessment",
            "max_score": Decimal("-0.01"),
        }

        with self.assertRaises(ValidationError):
            Assessment(**fields).full_clean()

        self.assert_database_rejects(Assessment, **fields)
