from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from . import test_scoring
from .materialized_views import refresh_materialized_views


class MeasureDbTests(TestCase):
    setUpTestData = classmethod(test_scoring.ElifExampleTests.setUpTestData.__func__)

    def test_reports_every_table_and_both_settings(self):
        refresh_materialized_views()
        out = StringIO()

        call_command("measure_db", runs=2, stdout=out)

        text = out.getvalue()
        for name in ("grading_grade", "auth_user", "cross_course_po_scores", "student_lo_scores"):
            self.assertIn(f"`{name}`", text)
        self.assertIn("| Grades of one enrollment |", text)
        self.assertIn("Seq Scan", text)
        self.assertNotIn("—", text)

    def test_empty_database_says_what_to_run(self):
        from grading.models import Enrollment

        Enrollment.objects.all().delete()
        with self.assertRaisesMessage(CommandError, "fake_data"):
            call_command("measure_db", runs=1, stdout=StringIO())
