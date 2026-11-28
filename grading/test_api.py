from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .access import STUDENT
from .models import (
    Assessment,
    AssessmentLOWeight,
    Course,
    CourseOffering,
    Enrollment,
    Grade,
    LearningOutcome,
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
