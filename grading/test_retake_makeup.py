"""Retakes and makeup exams (#104, #105, decision 0011).

Each case checks the calculation service, the explanation and the score
tables against each other, and the tables after the signal-driven refresh
against a full rebuild.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.test import TestCase
from django.urls import reverse

from .access import STUDENT
from .explain import explain_all, explain_po
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
    POComponent,
    ProgramOutcome,
    Term,
)
from .services import lo_scores, student_po_scores
from .test_materialized_views import TOL, rows
from .test_score_tables import snapshot

D = Decimal


class RetakeAndMakeupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = get_user_model().objects.create_user("s1")
        cls.student.groups.add(Group.objects.get_or_create(name=STUDENT)[0])
        cls.po = ProgramOutcome.objects.create(code="PO1")
        cls.component = POComponent.objects.create(program_outcome=cls.po, code="a")
        cls.course = Course.objects.create(code="CSE201", name="Algorithms", ects=6)
        # A second course keeps the PO score from being one course only.
        cls.other = Course.objects.create(code="CSE102", name="Programming", ects=6)

    def offering(self, course, year, season):
        term, _ = Term.objects.get_or_create(year=year, season=season)
        offering = CourseOffering.objects.create(course=course, term=term, ects=course.ects)
        lo1 = LearningOutcome.objects.create(offering=offering, code="LO1")
        lo2 = LearningOutcome.objects.create(offering=offering, code="LO2")
        for lo in (lo1, lo2):
            LOPOWeight.objects.create(learning_outcome=lo, component=self.component, weight=3)
        final = Assessment.objects.create(offering=offering, name="Final")
        AssessmentLOWeight.objects.create(assessment=final, learning_outcome=lo1, weight=1)
        AssessmentLOWeight.objects.create(assessment=final, learning_outcome=lo2, weight=1)
        return offering

    def grade(self, offering, name, score, status=Grade.Status.GRADED):
        enrollment, _ = Enrollment.objects.get_or_create(offering=offering, student=self.student)
        Grade.objects.create(
            enrollment=enrollment, assessment=offering.assessments.get(name=name),
            score=score, status=status,
        )

    def makeup(self, offering, los=("LO1", "LO2")):
        final = offering.assessments.get(name="Final")
        makeup = Assessment.objects.create(offering=offering, name="Makeup", replaces=final)
        for code in los:
            AssessmentLOWeight.objects.create(
                assessment=makeup, learning_outcome=offering.learning_outcomes.get(code=code), weight=1,
            )
        return makeup

    def po1(self):
        """PO1 from the service, checked against the explanation and the tables."""
        service = student_po_scores(self.student).get("PO1")
        explanation = explain_po(self.student, "PO1")
        self.assertEqual(service is None, explanation is None)
        if service is not None:
            self.assertLess(abs(explanation.score - service), TOL)
        incremental = snapshot()
        refresh_materialized_views()
        self.assertEqual(incremental, snapshot(), "signal refresh differs from a full rebuild")
        table = rows(f"SELECT score FROM cross_course_po_scores WHERE student_id = {self.student.pk}")
        self.assertEqual(bool(table), service is not None)
        if service is not None:
            self.assertLess(abs(table[0][0] - service), TOL)
        return service

    def setUp(self):
        connection.run_on_commit.clear()

    def run_commits(self, fn):
        connection.run_on_commit.clear()
        with self.captureOnCommitCallbacks(execute=True), transaction.atomic():
            fn()

    # Retakes (#104)

    def test_only_the_last_attempt_counts(self):
        def setup():
            self.grade(self.offering(self.course, 2025, "fall"), "Final", 40)
            self.grade(self.offering(self.course, 2026, "spring"), "Final", 75)
        self.run_commits(setup)
        self.assertLess(abs(self.po1() - 75), TOL)

    def test_both_attempts_keep_their_own_scores(self):
        def setup():
            self.first = self.offering(self.course, 2025, "fall")
            self.second = self.offering(self.course, 2026, "spring")
            self.grade(self.first, "Final", 40)
            self.grade(self.second, "Final", 75)
        self.run_commits(setup)
        for offering, want in ((self.first, 40), (self.second, 75)):
            enrollment = Enrollment.objects.get(offering=offering)
            self.assertEqual(set(lo_scores(enrollment).values()), {D(want)})

    def test_retake_counts_once_next_to_another_course(self):
        def setup():
            self.grade(self.offering(self.course, 2025, "fall"), "Final", 40)
            self.grade(self.offering(self.course, 2026, "spring"), "Final", 80)
            self.grade(self.offering(self.other, 2025, "fall"), "Final", 60)
        self.run_commits(setup)
        # Same ECTS, so the mean of 80 and 60; the failed 40 does not pull it down.
        self.assertLess(abs(self.po1() - 70), TOL)

    def test_attempt_without_grades_leaves_the_earlier_one(self):
        def setup():
            self.grade(self.offering(self.course, 2025, "fall"), "Final", 40)
            Enrollment.objects.create(offering=self.offering(self.course, 2026, "spring"), student=self.student)
        self.run_commits(setup)
        self.assertLess(abs(self.po1() - 40), TOL)

    def test_summer_comes_after_spring_whatever_the_ids(self):
        def setup():
            summer = self.offering(self.course, 2026, "summer")
            spring = self.offering(self.course, 2026, "spring")
            self.grade(spring, "Final", 30)
            self.grade(summer, "Final", 90)
        self.run_commits(setup)
        self.assertLess(abs(self.po1() - 90), TOL)

    def test_deleting_the_retake_brings_back_the_first_attempt(self):
        def setup():
            self.grade(self.offering(self.course, 2025, "fall"), "Final", 40)
            self.retake = self.offering(self.course, 2026, "spring")
            self.grade(self.retake, "Final", 75)
        self.run_commits(setup)
        self.run_commits(lambda: Enrollment.objects.filter(offering=self.retake).delete())
        self.assertLess(abs(self.po1() - 40), TOL)

    # Makeup exams (#105)

    def test_makeup_replaces_the_final_even_when_lower(self):
        def setup():
            offering = self.offering(self.course, 2026, "spring")
            self.makeup(offering)
            self.grade(offering, "Final", 70)
            self.grade(offering, "Makeup", 50)
        self.run_commits(setup)
        self.assertLess(abs(self.po1() - 50), TOL)

    def test_no_makeup_grade_keeps_the_final(self):
        def setup():
            offering = self.offering(self.course, 2026, "spring")
            self.makeup(offering)
            self.grade(offering, "Final", 70)
        self.run_commits(setup)
        self.assertLess(abs(self.po1() - 70), TOL)

    def test_absent_from_makeup_keeps_the_final(self):
        def setup():
            offering = self.offering(self.course, 2026, "spring")
            self.makeup(offering)
            self.grade(offering, "Final", 30)
            self.grade(offering, "Makeup", 0, status=Grade.Status.ABSENT)
        self.run_commits(setup)
        self.assertLess(abs(self.po1() - 30), TOL)

    def test_absent_from_final_then_makeup(self):
        def setup():
            offering = self.offering(self.course, 2026, "spring")
            self.makeup(offering)
            self.grade(offering, "Final", 0, status=Grade.Status.ABSENT)
            self.grade(offering, "Makeup", 65)
        self.run_commits(setup)
        self.assertLess(abs(self.po1() - 65), TOL)

    def test_makeup_feeds_only_its_own_los(self):
        def setup():
            self.offering_ = self.offering(self.course, 2026, "spring")
            self.makeup(self.offering_, los=("LO1",))
            self.grade(self.offering_, "Final", 70)
            self.grade(self.offering_, "Makeup", 50)
        self.run_commits(setup)
        enrollment = Enrollment.objects.get(offering=self.offering_)
        lo1 = self.offering_.learning_outcomes.get(code="LO1")
        # LO2 had only the final: replaced, so LO2 has no evidence left.
        self.assertEqual(lo_scores(enrollment), {lo1.pk: D(50)})
        self.assertLess(abs(self.po1() - 50), TOL)

    def test_adding_the_makeup_grade_later_updates_the_tables(self):
        def setup():
            self.offering_ = self.offering(self.course, 2026, "spring")
            self.makeup(self.offering_)
            self.grade(self.offering_, "Final", 30)
        self.run_commits(setup)
        self.assertLess(abs(self.po1() - 30), TOL)
        self.run_commits(lambda: self.grade(self.offering_, "Makeup", 60))
        self.assertLess(abs(self.po1() - 60), TOL)

    def test_replacement_must_stay_in_the_offering_and_not_chain(self):
        first = self.offering(self.course, 2025, "fall")
        second = self.offering(self.course, 2026, "spring")
        makeup = self.makeup(first)
        elsewhere = Assessment(offering=second, name="Makeup", replaces=first.assessments.get(name="Final"))
        with self.assertRaises(ValidationError):
            elsewhere.full_clean()
        chained = Assessment(offering=first, name="Second makeup", replaces=makeup)
        with self.assertRaises(ValidationError):
            chained.full_clean()

    # What a viewer sees

    def test_instructor_of_the_failed_attempt_does_not_see_it_counted(self):
        def setup():
            self.first = self.offering(self.course, 2025, "fall")
            self.grade(self.first, "Final", 40)
            self.grade(self.offering(self.course, 2026, "spring"), "Final", 75)
        self.run_commits(setup)
        only_first = Enrollment.objects.filter(offering=self.first)
        self.assertEqual(student_po_scores(self.student, only_first), {})
        self.assertEqual(explain_all(self.student, only_first), {})

    def test_profile_lists_both_attempts(self):
        def setup():
            self.grade(self.offering(self.course, 2025, "fall"), "Final", 40)
            self.grade(self.offering(self.course, 2026, "spring"), "Final", 75)
            Enrollment.objects.create(offering=self.offering(self.course, 2026, "fall"), student=self.student)
        self.run_commits(setup)
        self.client.force_login(self.student)
        page = self.client.get(reverse("student_profile", args=[self.student.pk])).content.decode()
        self.assertIn("Repeated courses", page)
        self.assertEqual(page.count("<th scope=\"row\">CSE201</th>"), 3)
        self.assertIn("replaced by a later attempt", page)
        self.assertIn("no grades yet", page)

    def test_profile_without_retakes_has_no_section(self):
        self.run_commits(lambda: self.grade(self.offering(self.course, 2026, "spring"), "Final", 75))
        self.client.force_login(self.student)
        page = self.client.get(reverse("student_profile", args=[self.student.pk])).content.decode()
        self.assertIn("program outcomes", page)
        self.assertNotIn("Repeated courses", page)
