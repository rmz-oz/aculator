"""Grades partitioned by term (#33): where rows land and what the database refuses."""

from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from .explain import explain_all
from .models import Assessment, Course, CourseOffering, Enrollment, Grade, GradeChange, Term


def partition_of(grade):
    with connection.cursor() as cursor:
        cursor.execute("SELECT tableoid::regclass::text FROM grading_grade WHERE id = %s", [grade.pk])
        return cursor.fetchone()[0]


def partitions():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
            "WHERE i.inhparent = 'grading_grade'::regclass"
        )
        return {row[0] for row in cursor.fetchall()}


class GradePartitionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.course = Course.objects.create(code="CSE321", name="Data Systems", ects=6)
        cls.fall = Term.objects.create(year=2026, season=Term.Season.FALL)
        cls.spring = Term.objects.create(year=2027, season=Term.Season.SPRING)
        cls.offering = CourseOffering.objects.create(course=cls.course, term=cls.fall)
        cls.assessment = Assessment.objects.create(offering=cls.offering, name="Midterm", max_score=D(100))
        cls.student = get_user_model().objects.create_user("elif")
        cls.enrollment = Enrollment.objects.create(offering=cls.offering, student=cls.student)

    def test_every_term_has_its_own_partition(self):
        # Terms created after the migration get one too, so their
        # grades never pile up in the default partition.
        names = partitions()
        for term in (self.fall, self.spring):
            self.assertIn(f"grading_grade_part_{term.pk}", names)

    def test_grade_lands_in_its_offerings_term(self):
        grade = Grade.objects.create(enrollment=self.enrollment, assessment=self.assessment, score=D(70))
        self.assertEqual(grade.term_id, self.fall.pk)
        self.assertEqual(partition_of(grade), f"grading_grade_part_{self.fall.pk}")

    def test_database_refuses_a_term_that_does_not_match_the_enrollment(self):
        grade = Grade(enrollment=self.enrollment, assessment=self.assessment, score=D(70), term=self.spring)
        with self.assertRaises(DatabaseError), transaction.atomic():
            grade.save()

    def test_form_refuses_moving_a_grade_to_a_course_in_another_term(self):
        # The admin runs full_clean(): a form error instead of a database error.
        grade = Grade.objects.create(enrollment=self.enrollment, assessment=self.assessment, score=D(70))
        later = CourseOffering.objects.create(course=self.course, term=self.spring)
        grade.enrollment = Enrollment.objects.create(offering=later, student=self.student)
        grade.assessment = Assessment.objects.create(offering=later, name="Midterm", max_score=D(100))
        with self.assertRaises(ValidationError) as caught:
            grade.full_clean()
        self.assertIn("enrollment", caught.exception.message_dict)

    def test_a_term_changed_in_memory_is_refused_not_saved_twice(self):
        # The UPDATE names the term the row was loaded with; saving another
        # term would otherwise update nothing and insert a second row.
        grade = Grade.objects.create(enrollment=self.enrollment, assessment=self.assessment, score=D(70))
        grade = Grade.objects.get(pk=grade.pk)
        grade.term = self.spring
        with self.assertRaises(ValueError):
            grade.save()
        self.assertEqual(Grade.objects.filter(pk=grade.pk).count(), 1)

    def test_deleting_a_term_drops_its_empty_partition(self):
        term = Term.objects.create(year=2030, season=Term.Season.FALL)
        self.assertIn(f"grading_grade_part_{term.pk}", partitions())
        term_id = term.pk
        term.delete()
        self.assertNotIn(f"grading_grade_part_{term_id}", partitions())

    def test_explanation_reads_grades_from_every_term_of_the_student(self):
        Grade.objects.create(enrollment=self.enrollment, assessment=self.assessment, score=D(70))
        later = CourseOffering.objects.create(course=Course.objects.create(code="CSE331", name="Systems", ects=5),
                                              term=self.spring)
        Grade.objects.create(enrollment=Enrollment.objects.create(offering=later, student=self.student),
                             assessment=Assessment.objects.create(offering=later, name="Final", max_score=D(100)),
                             score=D(80))
        with CaptureQueriesContext(connection) as queries:
            explain_all(self.student)
        [grades_sql] = [q["sql"] for q in queries if 'FROM "grading_grade"' in q["sql"]]
        for term in (self.fall, self.spring):
            self.assertIn(str(term.pk), grades_sql.split('"term_id" IN')[1].split(")")[0])

    def test_saving_a_grade_updates_only_its_terms_partition(self):
        # By id alone PostgreSQL would plan and lock every partition.
        grade = Grade.objects.create(enrollment=self.enrollment, assessment=self.assessment, score=D(70))
        grade.score = D(71)
        with CaptureQueriesContext(connection) as queries:
            grade.save()
        [update] = [q["sql"] for q in queries if q["sql"].startswith("UPDATE")]
        self.assertIn('"term_id" = ', update.split("WHERE")[1])

    def test_grade_history_still_records_changes(self):
        grade = Grade.objects.create(enrollment=self.enrollment, assessment=self.assessment, score=D(70))
        grade.score = D(75)
        grade.save()
        actions = list(GradeChange.objects.filter(grade_id=grade.pk).order_by("id").values_list("action", flat=True))
        self.assertEqual(actions, ["created", "updated"])

    def test_forms_refuse_moving_what_has_grades(self):
        # The database refuses it (the grades would sit in the wrong term);
        # full_clean() says so first, so the admin shows a form error.
        Grade.objects.create(enrollment=self.enrollment, assessment=self.assessment, score=D(70))
        other = CourseOffering.objects.create(course=Course.objects.create(code="CSE331", name="Systems", ects=5),
                                              term=self.fall)
        cases = (
            (CourseOffering.objects.get(pk=self.offering.pk), "term", self.spring),
            (Enrollment.objects.get(pk=self.enrollment.pk), "offering", other),
            (Assessment.objects.get(pk=self.assessment.pk), "offering", other),
        )
        for obj, field, value in cases:
            with self.subTest(model=type(obj).__name__):
                setattr(obj, field, value)
                with self.assertRaises(ValidationError) as caught:
                    obj.full_clean()
                self.assertIn(field, caught.exception.message_dict)
