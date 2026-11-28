from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .access import HEAD, INSTRUCTOR, STUDENT
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


class ReadOnlyApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.student = users.create_user(username="api-student")
        other_student = users.create_user(username="api-other-student")
        student_group, _ = Group.objects.get_or_create(name=STUDENT)
        cls.student.groups.add(student_group)
        other_student.groups.add(student_group)
        cls.token = Token.objects.create(user=cls.student)

        term = Term.objects.create(year=2026, season=Term.Season.FALL)
        course = Course.objects.create(code="API101", name="API Test", ects=6)
        offering = CourseOffering.objects.create(course=course, term=term, ects=6)
        cls.outcome = LearningOutcome.objects.create(offering=offering, code="LO1")
        assessment = Assessment.objects.create(
            offering=offering,
            name="Final",
            max_score=Decimal(100),
        )
        AssessmentLOWeight.objects.create(
            assessment=assessment,
            learning_outcome=cls.outcome,
            weight=Decimal(1),
        )
        cls.enrollment = Enrollment.objects.create(offering=offering, student=cls.student)
        other_enrollment = Enrollment.objects.create(offering=offering, student=other_student)
        Grade.objects.create(
            enrollment=cls.enrollment,
            assessment=assessment,
            score=Decimal(80),
        )
        Grade.objects.create(
            enrollment=other_enrollment,
            assessment=assessment,
            score=Decimal(65),
        )

    def authenticate(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def test_data_endpoints_require_token(self):
        for endpoint in (
            "api-courses",
            "api-offerings",
            "api-learning-outcomes",
            "api-program-outcomes",
            "api-scores",
            "api-outcome-scores",
        ):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.client.get(reverse(endpoint)).status_code, 401)

    def test_student_can_read_courses_and_learning_outcomes(self):
        self.authenticate()

        courses = self.client.get(reverse("api-courses"))
        self.assertEqual(courses.status_code, 200)
        self.assertEqual(courses.data["results"][0]["code"], "API101")

        outcomes = self.client.get(reverse("api-learning-outcomes"))
        self.assertEqual(outcomes.status_code, 200)
        self.assertEqual(outcomes.data["results"][0]["id"], self.outcome.pk)

    def test_student_sees_only_own_scores(self):
        self.authenticate()

        grades = self.client.get(reverse("api-scores"))
        self.assertEqual(grades.status_code, 200)
        self.assertEqual(grades.data["count"], 1)
        grade = grades.data["results"][0]
        self.assertEqual(grade["student"], self.student.pk)
        self.assertEqual(grade["score"], "80.00")

        outcomes = self.client.get(reverse("api-outcome-scores"))
        self.assertEqual(outcomes.status_code, 200)
        self.assertEqual(outcomes.data["count"], 1)
        row = outcomes.data["results"][0]
        self.assertEqual(row["enrollment"], self.enrollment.pk)
        self.assertEqual(Decimal(row["learning_outcomes"][str(self.outcome.pk)]), Decimal(80))

    def test_scores_reject_writes(self):
        self.authenticate()

        response = self.client.post(reverse("api-scores"), {"score": "75.00"})

        self.assertEqual(response.status_code, 405)
        self.assertEqual(Grade.objects.count(), 2)

    def test_schema_documents_token_auth_and_docs_load(self):
        schema = self.client.get(reverse("api-schema"), {"format": "json"})
        self.assertEqual(schema.status_code, 200)
        scores = schema.data["paths"][reverse("api-scores")]["get"]
        self.assertIn({"tokenAuth": []}, scores["security"])
        self.assertEqual(
            schema.data["components"]["securitySchemes"]["tokenAuth"]["name"],
            "Authorization",
        )

        docs = self.client.get(reverse("api-docs"))
        self.assertContains(docs, reverse("api-schema"))


class ApiAccessMatrixTests(APITestCase):
    """Who sees what: the same rules as the pages (decision 0007), and the retake and makeup flags (decision 0011)."""

    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        groups = {name: Group.objects.get_or_create(name=name)[0] for name in (STUDENT, INSTRUCTOR, HEAD)}

        def user(name, group=None):
            u = users.create_user(username=name)
            if group:
                u.groups.add(groups[group])
            return u

        cls.student, cls.other_student = user("s1", STUDENT), user("s2", STUDENT)
        cls.teacher, cls.other_teacher = user("t1", INSTRUCTOR), user("t2", INSTRUCTOR)
        cls.head, cls.nobody = user("h1", HEAD), user("n1")
        po = ProgramOutcome.objects.create(code="PO1")
        component = POComponent.objects.create(program_outcome=po, code="a")
        course = Course.objects.create(code="CSE201", name="Algorithms", ects=6)
        cls.offerings = []
        for year, season in ((2025, Term.Season.FALL), (2026, Term.Season.SPRING)):
            term = Term.objects.create(year=year, season=season)
            offering = CourseOffering.objects.create(course=course, term=term, ects=6)
            lo = LearningOutcome.objects.create(offering=offering, code="LO1")
            LOPOWeight.objects.create(learning_outcome=lo, component=component, weight=3)
            final = Assessment.objects.create(offering=offering, name="Final")
            AssessmentLOWeight.objects.create(assessment=final, learning_outcome=lo, weight=1)
            cls.offerings.append((offering, final, lo))
        first, second = cls.offerings
        first[0].instructors.add(cls.teacher)
        second[0].instructors.add(cls.other_teacher)
        # s1 failed in 2025 Fall and retook it; in 2026 Spring a makeup replaced the final.
        e1 = Enrollment.objects.create(offering=first[0], student=cls.student)
        e2 = Enrollment.objects.create(offering=second[0], student=cls.student)
        e3 = Enrollment.objects.create(offering=first[0], student=cls.other_student)
        makeup = Assessment.objects.create(offering=second[0], name="Makeup", replaces=second[1])
        AssessmentLOWeight.objects.create(assessment=makeup, learning_outcome=second[2], weight=1)
        cls.failed = Grade.objects.create(enrollment=e1, assessment=first[1], score=Decimal(30))
        cls.replaced = Grade.objects.create(enrollment=e2, assessment=second[1], score=Decimal(40))
        cls.makeup = Grade.objects.create(enrollment=e2, assessment=makeup, score=Decimal(70))
        Grade.objects.create(enrollment=e3, assessment=first[1], score=Decimal(90))
        cls.e1, cls.e2 = e1, e2

    def get(self, user, endpoint):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.get_or_create(user=user)[0].key}")
        response = self.client.get(reverse(endpoint))
        self.assertEqual(response.status_code, 200)
        return response.data["results"]

    def grade_ids(self, user):
        return {row["id"] for row in self.get(user, "api-scores")}

    def test_who_sees_which_grades(self):
        all_grades = set(Grade.objects.values_list("pk", flat=True))
        self.assertEqual(self.grade_ids(self.student), {self.failed.pk, self.replaced.pk, self.makeup.pk})
        self.assertEqual(self.grade_ids(self.teacher), set(Grade.objects.filter(
            enrollment__offering=self.offerings[0][0]).values_list("pk", flat=True)))
        self.assertEqual(self.grade_ids(self.other_teacher), {self.replaced.pk, self.makeup.pk})
        self.assertEqual(self.grade_ids(self.head), all_grades)
        self.assertEqual(self.grade_ids(self.nobody), set())

    def test_instructor_does_not_see_other_courses(self):
        offerings = {row["id"] for row in self.get(self.teacher, "api-offerings")}
        self.assertEqual(offerings, {self.offerings[0][0].pk})
        scores = self.get(self.teacher, "api-outcome-scores")
        self.assertNotIn(self.e2.pk, {row["enrollment"] for row in scores})

    def test_replaced_final_does_not_count(self):
        counts = {row["id"]: row["counts"] for row in self.get(self.student, "api-scores")}
        self.assertEqual(counts, {self.failed.pk: True, self.replaced.pk: False, self.makeup.pk: True})

    def test_only_the_last_attempt_counts_across_courses(self):
        rows = {row["enrollment"]: row for row in self.get(self.student, "api-outcome-scores")}
        self.assertFalse(rows[self.e1.pk]["counts_across_courses"])
        self.assertTrue(rows[self.e2.pk]["counts_across_courses"])
        self.assertEqual(Decimal(rows[self.e2.pk]["program_outcomes"]["PO1"]), Decimal(70))
        # The instructor of the failed attempt sees it as not counting too.
        rows = {row["enrollment"]: row for row in self.get(self.teacher, "api-outcome-scores")}
        self.assertFalse(rows[self.e1.pk]["counts_across_courses"])
