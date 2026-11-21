"""Each grade stores its offering's term (#33), filled in on save. A wrong term is refused (test_partitioning)."""

from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Assessment, Course, CourseOffering, Enrollment, Grade, Term


class GradeTermTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.course = Course.objects.create(code="CSE321", name="Data Systems", ects=6)
        cls.fall = Term.objects.create(year=2026, season=Term.Season.FALL)
        cls.spring = Term.objects.create(year=2027, season=Term.Season.SPRING)
        cls.offering = CourseOffering.objects.create(course=cls.course, term=cls.fall)
        cls.assessment = Assessment.objects.create(offering=cls.offering, name="Midterm", max_score=D(100))
        cls.student = get_user_model().objects.create_user("elif")
        cls.enrollment = Enrollment.objects.create(offering=cls.offering, student=cls.student)

    def test_term_is_the_offerings_term(self):
        grade = Grade.objects.create(enrollment=self.enrollment, assessment=self.assessment, score=D(70))
        self.assertEqual(grade.term_id, self.fall.pk)


class GradeAdminTests(TestCase):
    setUpTestData = classmethod(GradeTermTests.setUpTestData.__func__)

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("admin"))

    def test_term_is_shown_but_cannot_be_edited(self):
        grade = Grade.objects.create(enrollment=self.enrollment, assessment=self.assessment, score=D(70))
        page = self.client.get(f"/admin/grading/grade/{grade.pk}/change/")
        self.assertContains(page, 'class="form-row field-term"')
        self.assertNotContains(page, 'name="term"')

    def test_score_edit_is_saved(self):
        grade = Grade.objects.create(enrollment=self.enrollment, assessment=self.assessment, score=D(70))
        response = self.client.post(f"/admin/grading/grade/{grade.pk}/change/", {
            "enrollment": self.enrollment.pk, "assessment": self.assessment.pk, "status": "graded", "score": "75",
        })
        self.assertEqual(response.status_code, 302)
        grade.refresh_from_db()
        self.assertEqual(grade.score, D(75))

    def test_a_second_grade_for_the_same_student_is_a_form_error(self):
        Grade.objects.create(enrollment=self.enrollment, assessment=self.assessment, score=D(70))
        response = self.client.post("/admin/grading/grade/add/", {
            "enrollment": self.enrollment.pk, "assessment": self.assessment.pk, "status": "graded", "score": "80",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")
