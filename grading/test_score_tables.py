"""The score tables follow each change for its offering only (#79).

Every test changes something with the commit callbacks running and no full
refresh, then checks the tables against the calculation service and against
a full rebuild: same rows, same numbers.
"""

import random
import threading
from collections import defaultdict
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from .access import INSTRUCTOR, STUDENT
from .materialized_views import refresh_materialized_views, refresh_scores
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
from .services import course_po_scores, department_po_scores, lo_scores, student_po_scores
from .test_materialized_views import TOL, MaterializedViewTests, rows

D = Decimal
TABLES = ("student_lo_scores", "student_component_scores", "cross_course_po_scores", "department_po_means")


def snapshot():
    return {table: sorted(rows(f"SELECT * FROM {table}")) for table in TABLES}


class MatchesService:
    def assertClose(self, a, b, msg=None):
        self.assertLess(abs(a - b), TOL, msg or f"{a} != {b}")

    def assertScoresMatch(self):
        for enrollment in Enrollment.objects.all():
            where = f"WHERE student_id = {enrollment.student_id} AND offering_id = {enrollment.offering_id}"
            for got, want in (
                (dict(rows(f"SELECT learning_outcome_id, score FROM student_lo_scores {where}")),
                 lo_scores(enrollment)),
                (dict(rows(
                    "SELECT p.code, v.score FROM course_po_scores v "
                    f"JOIN grading_programoutcome p ON p.id = v.program_outcome_id {where.replace('WHERE ', 'WHERE v.')}"
                )), course_po_scores(enrollment)),
            ):
                self.assertEqual(got.keys(), want.keys(), enrollment)
                for key in want:
                    self.assertClose(got[key], want[key])

        users = get_user_model().objects
        per_po = defaultdict(list)
        for student in users.filter(enrollments__isnull=False).distinct():
            want = student_po_scores(student)
            got = dict(rows(
                "SELECT p.code, v.score FROM cross_course_po_scores v "
                f"JOIN grading_programoutcome p ON p.id = v.program_outcome_id WHERE v.student_id = {student.pk}"
            ))
            self.assertEqual(got.keys(), want.keys(), student)
            for code, score in want.items():
                self.assertClose(got[code], score)
                per_po[code].append(score)
        # Nobody without an enrollment keeps a row.
        self.assertEqual(
            rows("SELECT count(*) FROM cross_course_po_scores s WHERE NOT EXISTS "
                 "(SELECT 1 FROM grading_enrollment e WHERE e.student_id = s.student_id)")[0][0],
            0,
        )

        department = department_po_scores(min_students=1)
        self.assertEqual(department.keys(), per_po.keys())
        for code, scores in per_po.items():
            self.assertClose(department[code], sum(scores) / len(scores))

        # And exactly what a full rebuild gives, so no row is left behind.
        before = snapshot()
        refresh_materialized_views()
        self.assertEqual(snapshot(), before)


class IncrementalScoreTests(MatchesService, TestCase):
    @classmethod
    def setUpTestData(cls):
        MaterializedViewTests.setUpTestData.__func__(cls)
        # A second student in both courses, so cross-course rows are shared.
        cls.can = get_user_model().objects.create_user(username="can")
        cls.math = CourseOffering.objects.get(course__code="MAT241")
        cls.can_cse = Enrollment.objects.create(offering=cls.offering, student=cls.can)
        cls.can_math = Enrollment.objects.create(offering=cls.math, student=cls.can)
        Grade.objects.create(enrollment=cls.can_cse, assessment=cls.midterm, score=D(55))
        Grade.objects.create(enrollment=cls.can_cse, assessment=cls.project, score=D(70))
        Grade.objects.create(enrollment=cls.can_math, assessment=cls.math.assessments.get(), score=D(20))

    def setUp(self):
        connection.run_on_commit.clear()
        refresh_materialized_views()
        self.assertScoresMatch()

    def change(self, func):
        with self.captureOnCommitCallbacks(execute=True) as callbacks, transaction.atomic():
            func()
        self.assertEqual(len(callbacks), 1)
        self.assertScoresMatch()

    def grade(self, enrollment, assessment):
        return Grade.objects.get(enrollment=enrollment, assessment=assessment)

    def test_score_change(self):
        def edit():
            grade = self.grade(self.can_cse, self.midterm)
            grade.score = D("99.5")
            grade.save()
        self.change(edit)

    def test_marked_absent(self):
        def edit():
            grade = self.grade(self.can_cse, self.project)
            grade.status, grade.score = Grade.Status.ABSENT, D(0)
            grade.save()
        self.change(edit)

    def test_new_and_deleted_grades(self):
        def edit():
            self.grade(self.can_cse, self.project).delete()
            final = Assessment.objects.create(offering=self.offering, name="Final", max_score=D(40))
            AssessmentLOWeight.objects.create(assessment=final, learning_outcome=self.lo2, weight=D("0.5"))
            Grade.objects.create(enrollment=self.can_cse, assessment=final, score=D(30))
        self.change(edit)

    def test_assessment_deleted_with_its_grades(self):
        self.change(lambda: self.project.delete())

    def test_student_leaves_one_course(self):
        self.change(lambda: self.can_cse.delete())

    def test_student_leaves_every_course(self):
        def edit():
            self.can_cse.delete()
            self.can_math.delete()
        self.change(edit)
        self.assertEqual(rows(f"SELECT count(*) FROM cross_course_po_scores WHERE student_id = {self.can.pk}"),
                         [(0,)])

    def test_learning_outcome_deleted(self):
        self.change(lambda: self.lo1.delete())

    def test_learning_outcome_moves_to_another_offering(self):
        def edit():
            self.lo2.offering = self.math
            self.lo2.save()
        self.change(edit)

    def test_weight_set_to_zero(self):
        def edit():
            weight = AssessmentLOWeight.objects.filter(learning_outcome=self.lo1).first()
            weight.weight = D(0)
            weight.save()
        self.change(edit)

    def test_weight_moves_to_another_lo(self):
        def edit():
            weight = AssessmentLOWeight.objects.get(assessment=self.project, learning_outcome=self.lo1)
            weight.learning_outcome = LearningOutcome.objects.create(offering=self.offering, code="LO9")
            weight.save()
        self.change(edit)

    def test_lo_po_link_removed_and_added(self):
        def edit():
            LOPOWeight.objects.filter(learning_outcome=self.lo1).first().delete()
            other = POComponent.objects.create(program_outcome=self.po2, code="b")
            LOPOWeight.objects.create(learning_outcome=self.lo2, component=other, weight=5)
        self.change(edit)

    def test_offering_ects_change(self):
        def edit():
            self.math.ects = 10
            self.math.save()
        self.change(edit)

    def test_po_component_deleted(self):
        self.change(lambda: self.component1.delete())

    def test_po_component_added(self):
        def edit():
            component = POComponent.objects.create(program_outcome=self.po1, code="z")
            LOPOWeight.objects.create(learning_outcome=self.lo1, component=component, weight=2)
        self.change(edit)

    def test_new_offering_in_one_transaction(self):
        def edit():
            course = Course.objects.create(code="PHY101", name="Physics", ects=4)
            offering = CourseOffering.objects.create(course=course, term=self.term)
            lo = LearningOutcome.objects.create(offering=offering, code="LO1")
            LOPOWeight.objects.create(learning_outcome=lo, component=self.component2, weight=3)
            lab = Assessment.objects.create(offering=offering, name="Lab", max_score=D(10))
            AssessmentLOWeight.objects.create(assessment=lab, learning_outcome=lo, weight=D(1))
            for student, score in ((self.elif_, 7), (self.can, 4)):
                enrollment = Enrollment.objects.create(offering=offering, student=student)
                Grade.objects.create(enrollment=enrollment, assessment=lab, score=D(score))
        self.change(edit)

    def test_offering_deleted(self):
        math_id = self.math.pk
        self.change(lambda: self.math.delete())
        self.assertEqual(rows(f"SELECT count(*) FROM student_lo_scores WHERE offering_id = {math_id}"),
                         [(0,)])

    def test_deferred_fields_cost_no_query(self):
        # Loading a grade must not read back fields left out of the query.
        with self.assertNumQueries(1):
            list(Grade.objects.only("id"))

    def test_one_save_on_its_own(self):
        grade = self.grade(self.can_cse, self.midterm)
        grade.score = D(1)
        with self.captureOnCommitCallbacks(execute=True):
            grade.save()
        self.assertScoresMatch()


class ConcurrentImportTests(MatchesService, TransactionTestCase):
    """Two instructors import grades of two courses that share students at the same time."""

    def setUp(self):
        term = Term.objects.create(year=2026, season=Term.Season.FALL)
        component = POComponent.objects.create(program_outcome=ProgramOutcome.objects.create(code="PO1"), code="a")
        instructor_group = Group.objects.get_or_create(name=INSTRUCTOR)[0]
        student_group = Group.objects.get_or_create(name=STUDENT)[0]
        users = get_user_model().objects
        self.students = [users.create_user(username=f"2024{i:04d}") for i in range(40)]
        for student in self.students:
            student.groups.add(student_group)
        self.courses = []
        for code in ("CSE101", "MAT101"):
            offering = CourseOffering.objects.create(
                course=Course.objects.create(code=code, name=code, ects=5), term=term,
            )
            lo = LearningOutcome.objects.create(offering=offering, code="LO1")
            LOPOWeight.objects.create(learning_outcome=lo, component=component, weight=3)
            exam = Assessment.objects.create(offering=offering, name="Exam", max_score=D(100))
            AssessmentLOWeight.objects.create(assessment=exam, learning_outcome=lo, weight=D(1))
            for student in self.students:
                Enrollment.objects.create(offering=offering, student=student)
            teacher = users.create_user(username=f"teacher-{code}")
            teacher.groups.add(instructor_group)
            offering.instructors.add(teacher)
            self.courses.append((teacher, exam))

    def tearDown(self):
        # The flush after a TransactionTestCase only empties Django's tables.
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM student_lo_scores; DELETE FROM student_component_scores;"
                           " DELETE FROM cross_course_po_scores; REFRESH MATERIALIZED VIEW department_po_means")

    def test_imports_of_courses_sharing_students_all_succeed(self):
        statuses, errors = [], []

        def import_many(teacher, exam, seed):
            from django.test import Client

            client = Client()
            client.force_login(teacher)
            generator = random.Random(seed)
            try:
                for _ in range(6):
                    body = "student_number,score\n" + "".join(
                        f"{s.username},{generator.randint(0, 100)}\n" for s in self.students
                    )
                    upload = SimpleUploadedFile("g.csv", body.encode(), content_type="text/csv")
                    response = client.post(reverse("grade_import", args=[exam.pk]),
                                           {"csv_file": [upload], "action": "import"})
                    statuses.append(response.status_code)
            except Exception as error:  # noqa: BLE001, reported below
                errors.append(error)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=import_many, args=(*course, i)) for i, course in enumerate(self.courses)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        # 409 is the import's own answer to a serialization failure (decision
        # 0008): it happens here with the refresh switched off too, the two
        # imports read the same small tables. Anything else is a bug.
        self.assertEqual(len(statuses), 12)
        self.assertLessEqual(set(statuses), {200, 409})
        self.assertIn(200, statuses)
        self.assertScoresMatch()

    def test_refresh_runs_after_the_import_transaction(self):
        teacher, exam = self.courses[0]
        seen = []

        def check(offerings, students=(), using="default"):
            seen.append((set(offerings), connection.in_atomic_block))

        self.client.force_login(teacher)
        body = "student_number,score\n" + "".join(f"{s.username},50\n" for s in self.students)
        with mock.patch("grading.signals.refresh_scores", side_effect=check):
            response = self.client.post(
                reverse("grade_import", args=[exam.pk]),
                {"csv_file": [SimpleUploadedFile("g.csv", body.encode())], "action": "import"},
            )
        self.assertEqual(response.status_code, 200)
        # Once, for that offering, outside the SERIALIZABLE transaction.
        self.assertEqual(seen, [({exam.offering_id}, False)])

    def test_parallel_refreshes_wait_for_each_other(self):
        offerings = [exam.offering_id for _, exam in self.courses]
        for _, exam in self.courses:
            for student in self.students:
                Grade.objects.create(
                    enrollment=Enrollment.objects.get(offering_id=exam.offering_id, student=student),
                    assessment=exam, score=D(random.randint(0, 100)),
                )
        errors = []

        def refresh_many():
            try:
                for _ in range(15):
                    refresh_scores(offerings)
            except Exception as error:  # noqa: BLE001, reported below
                errors.append(error)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=refresh_many) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertScoresMatch()
