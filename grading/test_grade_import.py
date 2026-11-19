from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError
from django.test import TransactionTestCase
from django.urls import reverse
from psycopg.errors import SerializationFailure

from .access import INSTRUCTOR
from .models import Assessment, Course, CourseOffering, Enrollment, Grade, Term


class GradeImportTests(TransactionTestCase):
    def test_invalid_score_leaves_existing_grade_unchanged(self):
        term = Term.objects.create(year=2026, season=Term.Season.FALL)
        course = Course.objects.create(code="CSE101", name="Programming", ects=6)
        offering = CourseOffering.objects.create(course=course, term=term)
        assessment = Assessment.objects.create(
            offering=offering, name="Final", max_score=Decimal(100)
        )

        users = get_user_model().objects
        instructor = users.create_user(username="csv-instructor")
        group, _ = Group.objects.get_or_create(name=INSTRUCTOR)
        instructor.groups.add(group)
        offering.instructors.add(instructor)
        self.client.force_login(instructor)

        first = Enrollment.objects.create(
            offering=offering, student=users.create_user(username="20230001")
        )
        second = Enrollment.objects.create(
            offering=offering, student=users.create_user(username="20230002")
        )
        grade = Grade.objects.create(
            assessment=assessment, enrollment=first, score=Decimal("74.80")
        )

        broken_csv = SimpleUploadedFile(
            "bozuk-notlar.csv",
            b"student_number,score\n20230001,75\n20230002,abc\n",
            content_type="text/csv",
        )
        response = self.client.post(
            reverse("grade_import", args=[assessment.pk]),
            {"csv_file": broken_csv},
        )

        self.assertContains(response, "3. satır: Puan sayı olmalı.")
        grade.refresh_from_db()
        self.assertEqual(grade.score, Decimal("74.80"))
        self.assertFalse(
            Grade.objects.filter(assessment=assessment, enrollment=second).exists()
        )

    def test_serialization_failure_asks_user_to_retry(self):
        error = OperationalError("CSV import transaction aborted")
        error.__cause__ = SerializationFailure("Concurrent transaction")

        with patch("grading.views._grade_import", side_effect=error):
            response = self.client.post(reverse("grade_import", args=[1]))

        self.assertContains(
            response,
            "CSV dosyalarını yeniden seçip tekrar dene.",
            status_code=409,
        )