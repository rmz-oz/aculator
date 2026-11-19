import re
from decimal import Decimal
from unittest.mock import patch

import psycopg
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TransactionTestCase
from django.urls import reverse

from . import views
from .access import HEAD, INSTRUCTOR, STUDENT
from .models import Assessment, Course, CourseOffering, Enrollment, Grade, Term

D = Decimal
HEADER = b"student_number,score\n"


def csv_file(content, name="grades.csv"):
    return SimpleUploadedFile(name, content, content_type="text/csv")


# TransactionTestCase, not TestCase: the view sets the isolation level, which
# PostgreSQL only allows as the first statement of a real transaction.
class GradeImportTests(TransactionTestCase):
    def setUp(self):
        term = Term.objects.create(year=2026, season=Term.Season.FALL)
        course = Course.objects.create(code="CSE101", name="Programming", ects=6)
        self.offering = CourseOffering.objects.create(course=course, term=term)
        self.assessment = Assessment.objects.create(offering=self.offering, name="Final", max_score=D(50))
        self.url = reverse("grade_import", args=[self.assessment.pk])

        self.users = get_user_model().objects
        self.instructor = self.make_user("teacher", INSTRUCTOR)
        self.offering.instructors.add(self.instructor)
        self.enrollments = [
            Enrollment.objects.create(offering=self.offering, student=self.make_user(f"2023000{i}", STUDENT))
            for i in range(1, 4)
        ]
        self.client.force_login(self.instructor)

    def make_user(self, username, role):
        user = self.users.create_user(username=username)
        user.groups.add(Group.objects.get_or_create(name=role)[0])
        return user

    def grade(self, index):
        return Grade.objects.filter(assessment=self.assessment, enrollment=self.enrollments[index]).first()

    def upload(self, *files, action="import"):
        return self.client.post(self.url, {"csv_file": list(files), "action": action})

    def preview(self, *files):
        response = self.upload(*files, action="preview")
        self.assertEqual(response.status_code, 200)
        return re.search(r'name="preview_token" value="([^"]+)"', response.content.decode()).group(1)

    def confirm(self, token, absent=()):
        return self.client.post(
            self.url, {"action": "confirm", "preview_token": token, "absent_students": list(absent)}
        )

    def test_import_saves_and_overwrites_grades(self):
        Grade.objects.create(
            assessment=self.assessment, enrollment=self.enrollments[0], status=Grade.Status.ABSENT, score=0
        )
        response = self.upload(csv_file(HEADER + b"20230001,40.5\n20230002,50\n"))

        self.assertContains(response, "2 grades saved")
        self.assertEqual((self.grade(0).status, self.grade(0).score), (Grade.Status.GRADED, D("40.50")))
        self.assertEqual(self.grade(1).score, D(50))
        self.assertIsNone(self.grade(2))

    def test_invalid_score_leaves_existing_grade_unchanged(self):
        Grade.objects.create(assessment=self.assessment, enrollment=self.enrollments[0], score=D("34.80"))
        response = self.upload(csv_file(HEADER + b"20230001,45\n20230002,abc\n", "broken.csv"))

        self.assertContains(response, "broken.csv, line 3: Score must be a number.")
        self.assertEqual(self.grade(0).score, D("34.80"))
        self.assertIsNone(self.grade(1))

    def test_only_instructors_of_the_offering_may_import(self):
        head = self.make_user("head", HEAD)
        superuser = get_user_model().objects.create_superuser("root", password=None)
        other = self.make_user("other-teacher", INSTRUCTOR)
        for user in (head, superuser, other, self.enrollments[0].student):
            self.client.force_login(user)
            with self.subTest(user=user.username):
                self.assertEqual(self.client.get(self.url).status_code, 404)
                self.assertEqual(self.upload(csv_file(HEADER + b"20230001,10\n")).status_code, 404)
        self.assertFalse(Grade.objects.exists())

    def test_head_who_teaches_the_offering_may_import(self):
        head = self.make_user("teaching-head", HEAD)
        self.offering.instructors.add(head)
        self.client.force_login(head)
        self.assertContains(self.upload(csv_file(HEADER + b"20230001,10\n")), "1 grade saved")

    def test_logged_out_user_is_sent_to_login(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertRedirects(response, f"{reverse('login')}?next={self.url}", fetch_redirect_response=False)
        self.assertFalse(Grade.objects.exists())


    def test_header_and_number_variants(self):
        files = [
            csv_file(b"\xef\xbb\xbfStudent_Number , SCORE\r\n20230001,40.000\r\n", "bom.csv"),
            csv_file(b"score;student_number\n12,5;20230002\n", "excel-tr.csv"),
            csv_file(b"student_number,score\n\n20230003, 7 \n\n", "blank-lines.csv"),
        ]
        self.assertContains(self.upload(*files), "3 grades saved")
        self.assertEqual([self.grade(i).score for i in range(3)], [D(40), D("12.5"), D(7)])

    def test_row_errors_are_all_reported_and_nothing_is_saved(self):
        cases = {
            b"20230001,50.01\n": "line 2: Score must be between 0 and 50.00.",
            b"20230001,-1\n": "line 2: Score must be between 0 and 50.00.",
            b"20230001,NaN\n": "line 2: Score must be between 0 and 50.00.",
            b"20230001,10.005\n": "line 2: Score can have at most two decimal places.",
            b"20239999,10\n": "line 2: 20239999 is not enrolled in this course.",
            b",10\n": "line 2: Student number is empty.",
            b"20230001,10,extra\n": "line 2: Expected 2 columns, found 3.",
            b"20230001,10\n20230001,20\n": "line 3: 20230001 appears again, first at grades.csv, line 2.",
        }
        for rows, message in cases.items():
            with self.subTest(rows=rows):
                self.assertContains(self.upload(csv_file(HEADER + rows)), message)
        self.assertFalse(Grade.objects.exists())

    def test_file_errors(self):
        cases = [
            (b"", "empty.csv: File is empty."),
            (HEADER, "header-only.csv: File has no grade rows."),
            (b"number,score\n20230001,10\n", "wrong-header.csv: The first row must be student_number,score."),
            (b"student_number,score,name\n20230001,10,x\n", "extra.csv: The first row must be"),
            ("student_number,score\n20230001,10\nŞ,1\n".encode("cp1254"), "cp1254.csv: File is not UTF-8."),
            (HEADER + b'20230001,"10\n', "quote.csv: File could not be read"),
        ]
        for content, message in cases:
            name = message.split(":")[0]
            with self.subTest(name=name):
                self.assertContains(self.upload(csv_file(content, name)), message)
        self.assertContains(self.client.post(self.url, {"action": "import"}), "Choose at least one CSV file.")
        self.assertFalse(Grade.objects.exists())

    def test_large_file_is_rejected(self):
        with patch("grading.grade_import.MAX_FILE_SIZE", 10):
            response = self.upload(csv_file(HEADER + b"20230001,10\n", "big.csv"))
        self.assertContains(response, "big.csv: File is larger than 1 MB.")

    def test_student_in_two_files_is_an_error(self):
        response = self.upload(
            csv_file(HEADER + b"20230001,10\n", "a.csv"),
            csv_file(HEADER + b"20230002,20\n20230001,30\n", "b.csv"),
        )
        self.assertContains(response, "b.csv, line 3: 20230001 appears again, first at a.csv, line 2.")
        self.assertFalse(Grade.objects.exists())

    def test_preview_saves_nothing_and_confirm_marks_absent(self):
        Grade.objects.create(assessment=self.assessment, enrollment=self.enrollments[2], score=D(5))
        self.enrollments.append(
            Enrollment.objects.create(offering=self.offering, student=self.make_user("20230004", STUDENT))
        )
        response = self.upload(csv_file(HEADER + b"20230001,40\n20230003,45\n"), action="preview")

        self.assertContains(response, "2 grades will be saved, 1 of them replacing an existing grade.")
        self.assertContains(response, "20230003: 5.00 to 45.00")
        self.assertContains(response, 'value="20230002"')
        self.assertContains(response, 'value="20230004"')
        self.assertNotContains(response, 'value="20230003"')
        self.assertIsNone(self.grade(0))

        token = re.search(r'name="preview_token" value="([^"]+)"', response.content.decode()).group(1)
        response = self.confirm(token, absent=["20230002"])

        self.assertContains(response, "2 grades saved, 1 student marked absent.")
        self.assertEqual(self.grade(0).score, D(40))
        self.assertEqual((self.grade(1).status, self.grade(1).score), (Grade.Status.ABSENT, D(0)))
        self.assertEqual(self.grade(2).score, D(45))
        self.assertIsNone(self.grade(3))

    def test_preview_cannot_be_confirmed_twice(self):
        token = self.preview(csv_file(HEADER + b"20230001,40\n"))
        self.assertContains(self.confirm(token), "1 grade saved")
        Grade.objects.filter(pk=self.grade(0).pk).update(score=D(12))

        self.assertContains(self.confirm(token), "Grades for this assessment changed after the preview")
        self.assertEqual(self.grade(0).score, D(12))

    def test_confirm_rejects_tampered_or_foreign_token(self):
        token = self.preview(csv_file(HEADER + b"20230001,40\n"))
        self.assertContains(self.confirm(token[:-2] + "xx"), "The preview is invalid or has expired.")
        self.assertContains(self.confirm(token, absent=["20230001"]), "Only students suggested in the preview")

        other = self.make_user("co-teacher", INSTRUCTOR)
        self.offering.instructors.add(other)
        self.client.force_login(other)
        self.assertContains(self.confirm(token), "The preview is invalid or has expired.")
        self.assertFalse(Grade.objects.exists())

    def test_confirm_rejects_changed_enrollments_or_max_score(self):
        token = self.preview(csv_file(HEADER + b"20230001,40\n"))
        self.enrollments[2].delete()
        self.assertContains(self.confirm(token), "Enrollments in this course changed.")

        token = self.preview(csv_file(HEADER + b"20230001,40\n"))
        Assessment.objects.filter(pk=self.assessment.pk).update(max_score=D(45))
        self.assertContains(self.confirm(token), "The maximum score of this assessment changed.")
        self.assertFalse(Grade.objects.exists())

    def test_import_runs_at_serializable(self):
        seen = []

        def save_and_record(*args):
            with connection.cursor() as cursor:
                cursor.execute("SHOW transaction_isolation")
                seen.append(cursor.fetchone()[0])
            return save_scores(*args)

        save_scores = views._save_scores
        with patch("grading.views._save_scores", save_and_record):
            self.upload(csv_file(HEADER + b"20230001,40\n"))
        self.assertEqual(seen, ["serializable"])

    def test_serialization_failure_saves_nothing_and_asks_to_retry(self):
        # A second connection reads grade 1 and adds an enrollment while the
        # import has read the enrollments and is about to write grade 1. That
        # is a read/write cycle, so PostgreSQL aborts the import.
        settings = connection.settings_dict
        other = psycopg.connect(
            dbname=settings["NAME"], user=settings["USER"], password=settings["PASSWORD"],
            host=settings["HOST"], port=settings["PORT"],
        )
        self.addCleanup(other.close)
        late_student = self.make_user("20230009", STUDENT)

        def commit_other_then_save(*args):
            with other.cursor() as cursor:
                cursor.execute("BEGIN ISOLATION LEVEL SERIALIZABLE")
                cursor.execute(
                    "SELECT score FROM grading_grade WHERE assessment_id = %s", [self.assessment.pk]
                )
                cursor.execute(
                    "INSERT INTO grading_enrollment (offering_id, student_id) VALUES (%s, %s)",
                    [self.offering.pk, late_student.pk],
                )
            other.commit()
            return save_scores(*args)

        save_scores = views._save_scores
        with patch("grading.views._save_scores", commit_other_then_save):
            response = self.upload(csv_file(HEADER + b"20230001,40\n"))

        self.assertContains(response, "Choose the files again.", status_code=409)
        self.assertFalse(Grade.objects.exists())
