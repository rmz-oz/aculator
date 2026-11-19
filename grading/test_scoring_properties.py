from decimal import Decimal
from fractions import Fraction

from django.test import SimpleTestCase
from hypothesis import example, given
from hypothesis import strategies as st

from .services import weighted_mean

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
