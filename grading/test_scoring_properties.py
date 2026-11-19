from decimal import Decimal
from fractions import Fraction

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from hypothesis import example, given, settings
from hypothesis import strategies as st
from hypothesis.extra.django import TestCase

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
from .services import scores_by_enrollment, weighted_mean

GRADES = st.decimals(min_value=0, max_value=100, places=2)
WEIGHTS = st.decimals(min_value=0, max_value=1, places=4)
POSITIVE_WEIGHTS = st.decimals(min_value="0.0001", max_value=1, places=4)


@st.composite
def weighted_pairs(draw):
    pairs = draw(st.lists(st.tuples(GRADES, WEIGHTS), max_size=29))
    index = draw(st.integers(min_value=0, max_value=len(pairs)))
    pairs.insert(index, (draw(GRADES), draw(POSITIVE_WEIGHTS)))
    return pairs


class WeightedMeanPropertyTests(SimpleTestCase):
    @given(weighted_pairs())
    @example([(Decimal(0), Decimal(1))])
    @example([(Decimal(100), Decimal(1))])
    def test_score_is_between_zero_and_one_hundred(self, pairs):
        score = weighted_mean(pairs)

        self.assertIsNotNone(score)
        self.assertLessEqual(Decimal(0), score)
        self.assertLessEqual(score, Decimal(100))

    @given(weighted_pairs())
    def test_score_matches_sum_of_reference_contributions(self, pairs):
        total_weight = sum(Fraction(weight) for _, weight in pairs)
        total = sum(Fraction(grade) * Fraction(weight) / total_weight for grade, weight in pairs)
        expected = Decimal(total.numerator) / Decimal(total.denominator)

        self.assertAlmostEqual(weighted_mean(pairs), expected, places=6)

    @given(
        weighted_pairs(),
        st.decimals(min_value="0.01", max_value=100, places=2),
    )
    def test_scaling_all_weights_preserves_score(self, pairs, factor):
        scaled_pairs = [(grade, weight * factor) for grade, weight in pairs]

        self.assertAlmostEqual(weighted_mean(scaled_pairs), weighted_mean(pairs), places=6)

    @given(st.lists(GRADES, max_size=30))
    @example([])
    def test_zero_total_weight_returns_none(self, grades):
        pairs = [(grade, Decimal(0)) for grade in grades]

        self.assertIsNone(weighted_mean(pairs))


# One assessment as (max score, share of it the student got, LO weight).
ASSESSMENTS = st.lists(
    st.tuples(
        st.decimals(min_value="0.01", max_value=1000, places=2),
        st.fractions(min_value=0, max_value=1),
        POSITIVE_WEIGHTS,
    ),
    min_size=1,
    max_size=5,
)


class EnginePropertyTests(TestCase):
    """The same properties through the database: grades out of any max score, LO, component and PO."""

    @classmethod
    def setUpTestData(cls):
        term = Term.objects.create(year=2026, season=Term.Season.FALL)
        course = Course.objects.create(code="CSE311", name="Software Engineering", ects=6)
        cls.offering = CourseOffering.objects.create(course=course, term=term)
        cls.lo = LearningOutcome.objects.create(offering=cls.offering, code="LO1")
        component = POComponent.objects.create(
            program_outcome=ProgramOutcome.objects.create(code="PO1"), code="a"
        )
        LOPOWeight.objects.create(learning_outcome=cls.lo, component=component, weight=3)
        student = get_user_model().objects.create_user(username="20230001")
        cls.enrollment = Enrollment.objects.create(offering=cls.offering, student=student)

    @settings(max_examples=40, deadline=None)
    @given(ASSESSMENTS)
    @example([(Decimal("0.01"), Fraction(1), Decimal(1))])
    @example([(Decimal(1000), Fraction(0), Decimal("0.0001"))])
    def test_lo_and_po_stay_in_range_and_match_contributions(self, assessments):
        contributions = []
        total_weight = sum(Fraction(weight) for _, _, weight in assessments)
        for index, (max_score, share, weight) in enumerate(assessments):
            assessment = Assessment.objects.create(offering=self.offering, name=f"A{index}", max_score=max_score)
            AssessmentLOWeight.objects.create(assessment=assessment, learning_outcome=self.lo, weight=weight)
            score = min(max_score, (max_score * Decimal(share.numerator) / share.denominator).quantize(Decimal("0.01")))
            Grade.objects.create(assessment=assessment, enrollment=self.enrollment, score=score)
            contributions.append(Fraction(score) / Fraction(max_score) * 100 * Fraction(weight) / total_weight)

        lo_scores, po_scores = scores_by_enrollment([self.enrollment])[self.enrollment.pk]
        expected = sum(contributions)

        for score in (lo_scores[self.lo.pk], po_scores["PO1"]):
            self.assertLessEqual(Decimal(0), score)
            self.assertLessEqual(score, Decimal(100))
            self.assertAlmostEqual(score, Decimal(expected.numerator) / Decimal(expected.denominator), places=6)
