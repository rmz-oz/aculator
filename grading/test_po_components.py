from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import LOPOWeight, POComponent, ProgramOutcome
from .services import (
    course_component_scores,
    course_po_report,
    course_po_scores,
    po_report,
)
from .test_scoring import ElifExampleTests


class POComponentReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.po = ProgramOutcome.objects.create(code="PO6")
        POComponent.objects.create(
            program_outcome=cls.po,
            code="a",
            description="Individual work",
        )
        POComponent.objects.create(
            program_outcome=cls.po,
            code="b",
            description="Teamwork",
        )

    def test_missing_evidence_blocks_po(self):
        result = po_report(
            {("PO6", "a"): Decimal(90)},
            threshold=60,
        )["PO6"]

        self.assertEqual(result["score"], Decimal(90))
        self.assertFalse(result["met"])
        self.assertIsNone(result["components"]["b"]["score"])
        self.assertEqual(
            result["components"]["b"]["status"],
            "no evidence",
        )

    def test_average_cannot_hide_weak_component(self):
        result = po_report(
            {
                ("PO6", "a"): Decimal(100),
                ("PO6", "b"): Decimal(40),
            },
            threshold=60,
        )["PO6"]

        self.assertEqual(result["score"], Decimal(70))
        self.assertFalse(result["met"])

    def test_every_component_must_reach_threshold(self):
        result = po_report(
            {
                ("PO6", "a"): Decimal(60),
                ("PO6", "b"): Decimal(80),
            },
            threshold=60,
        )["PO6"]

        self.assertEqual(result["score"], Decimal(70))
        self.assertTrue(result["met"])

    def test_zero_is_evidence(self):
        result = po_report(
            {
                ("PO6", "a"): Decimal(0),
                ("PO6", "b"): Decimal(80),
            },
            threshold=60,
        )["PO6"]

        self.assertEqual(result["score"], Decimal(40))
        self.assertEqual(
            result["components"]["a"]["status"],
            "not met",
        )

    def test_no_evidence_has_no_display_score(self):
        result = po_report({}, threshold=60)["PO6"]

        self.assertIsNone(result["score"])
        self.assertFalse(result["met"])

    def test_threshold_uses_unrounded_score(self):
        result = po_report(
            {
                ("PO6", "a"): Decimal("59.99"),
                ("PO6", "b"): Decimal(80),
            },
            threshold=60,
        )["PO6"]

        self.assertFalse(result["met"])

    def test_component_code_is_unique_within_po(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            POComponent.objects.create(
                program_outcome=self.po,
                code="a",
            )

    def test_same_component_code_is_allowed_for_another_po(self):
        other = ProgramOutcome.objects.create(code="PO7")
        component = POComponent.objects.create(
            program_outcome=other,
            code="a",
        )

        self.assertIsNotNone(component.pk)

    def test_po_without_components_is_not_met(self):
        ProgramOutcome.objects.create(code="PO8")

        result = po_report({}, threshold=60)["PO8"]

        self.assertIsNone(result["score"])
        self.assertFalse(result["met"])


class ComponentScoringTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ElifExampleTests.setUpTestData.__func__(cls)

    def test_component_scores_use_lo_contribution_levels(self):
        scores = course_component_scores(self.enrollment)
        lo2_score = (
            Decimal(90) * Decimal("0.4") + Decimal(80)
        ) / Decimal("1.4")
        expected = (
            Decimal(86) * Decimal(2) + lo2_score
        ) / Decimal(3)

        self.assertLess(
            abs(scores[("PO1", "a")] - expected),
            Decimal("1e-20"),
        )

    def test_component_scores_are_averaged_equally(self):
        component = POComponent.objects.create(
            program_outcome=self.po1,
            code="b",
        )
        LOPOWeight.objects.create(
            learning_outcome=self.lo1,
            component=component,
            weight=5,
        )

        components = course_component_scores(self.enrollment)
        expected = (
            components[("PO1", "a")]
            + components[("PO1", "b")]
        ) / Decimal(2)

        self.assertEqual(
            course_po_scores(self.enrollment)["PO1"],
            expected,
        )

    def test_unmapped_component_blocks_attainment(self):
        POComponent.objects.create(
            program_outcome=self.po1,
            code="b",
        )

        result = course_po_report(
            self.enrollment,
            threshold=60,
        )["PO1"]

        self.assertIsNotNone(result["score"])
        self.assertFalse(result["met"])
        self.assertEqual(
            result["components"]["b"]["status"],
            "no evidence",
        )