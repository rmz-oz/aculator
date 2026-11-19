from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from . import test_scoring
from .explain import explain_all, explain_po
from .services import display, student_po_scores

TOLERANCE = Decimal("1e-20")


class ElifExplanationTests(TestCase):
    setUpTestData = classmethod(test_scoring.ElifExampleTests.setUpTestData.__func__)

    def test_po1_splits_into_midterm_and_project(self):
        explanation = explain_po(self.elif_, "PO1")

        self.assertEqual(display(explanation.score), Decimal("85.0"))
        parts = {p.label: display(p.contribution) for p in explanation.by_assessment()}
        self.assertEqual(parts, {"Midterm": Decimal("44.6"), "Project": Decimal("40.4")})

    def test_contributions_add_up_exactly(self):
        explanation = explain_po(self.elif_, "PO1")

        total = sum(p.contribution for p in explanation.grades)
        self.assertLess(abs(total - explanation.score), TOLERANCE)
        self.assertLess(abs(sum(p.share for p in explanation.grades) - 1), TOLERANCE)
        self.assertLess(abs(sum(p.share for p in explanation.los) - 1), TOLERANCE)

    def test_po_without_evidence_has_no_explanation(self):
        self.assertIsNone(explain_po(self.elif_, "PO99"))


class ExplanationMatchesServiceTests(TestCase):
    """The explanation re-derives the score; it must agree with services.py for every student."""

    @classmethod
    def setUpTestData(cls):
        call_command("fake_data", students=40, seed=7, verbosity=0, stdout=None)

    def test_every_student_and_po(self):
        checked = 0
        for student in get_user_model().objects.filter(username__startswith="fake_student_"):
            scores = student_po_scores(student)
            explanations = explain_all(student)
            self.assertEqual(set(explanations), set(scores), student.username)
            for code, score in scores.items():
                explanation = explanations[code]
                self.assertEqual(explain_po(student, code).score, explanation.score)
                self.assertLess(abs(explanation.score - score), TOLERANCE, (student.username, code))
                total = sum(p.contribution for p in explanation.grades)
                self.assertLess(abs(total - score), TOLERANCE, (student.username, code))
                checked += 1
        self.assertGreater(checked, 100)
