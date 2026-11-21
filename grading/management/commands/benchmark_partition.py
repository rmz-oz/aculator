"""Time the app's own grade queries, for the partitioning section of the CSE 321 report (#33).

Run it on two databases with the same data, one with grades partitioned by
term and one without (docs/partitioning.md shows how to make the second), and
compare. Prints Markdown: median execution and planning time of EXPLAIN
(ANALYZE, BUFFERS) over --runs runs, and each query's plan.
"""

import json
import statistics

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import F

from grading.models import Assessment, Enrollment, Grade, Term


def sql_of(queryset):
    return queryset.query.sql_with_params()


class Command(BaseCommand):
    help = "Median EXPLAIN ANALYZE times of the app's grade queries (#33)."

    def add_arguments(self, parser):
        parser.add_argument("--runs", type=int, default=15)
        parser.add_argument("--warmup", type=int, default=3)

    def handle(self, *args, runs, warmup, **options):
        # The same rows in both databases: picked by natural keys, not ids.
        term = Term.objects.filter(grades__isnull=False).order_by("-year", "-season").first()
        if term is None:
            raise CommandError("No grades to measure. Run `python manage.py fake_data --years 10` first.")
        assessment = (
            Assessment.objects.filter(offering__term=term, grades__isnull=False)
            .order_by("offering__course__code", "name").first()
        )
        offering = assessment.offering
        class_enrollments = list(offering.enrollments.values_list("pk", flat=True))
        student_id = offering.enrollments.order_by("student__username").values_list("student_id", flat=True)[0]
        grade = Grade.objects.filter(assessment=assessment).order_by("enrollment_id").first()
        # As grading.services does: the terms are named, so only their partitions are read.
        terms_of_student = list(
            Enrollment.objects.filter(student_id=student_id).values_list("offering__term_id", flat=True).distinct()
        )

        queries = (
            ("Class report: grades of one offering", sql_of(
                Grade.objects.filter(term_id__in=[term.pk], enrollment_id__in=class_enrollments,
                                     assessment__offering_id=F("enrollment__offering_id"))
                .select_related("assessment"))),
            ("Student profile: grades of one student, every term", sql_of(
                Grade.objects.filter(term_id__in=terms_of_student,
                                     enrollment__in=Enrollment.objects.filter(student_id=student_id),
                                     assessment__offering_id=F("enrollment__offering_id"))
                .select_related("assessment"))),
            ("Grade import: grades of one assessment", sql_of(
                assessment.term_grades().order_by("enrollment_id").values_list("enrollment_id", "status", "score"))),
            ("Saving one grade: find it by enrollment, assessment and term", sql_of(
                Grade.objects.filter(assessment=assessment, enrollment_id=grade.enrollment_id, term_id=term.pk))),
            ("Admin: one grade by id", sql_of(Grade.objects.filter(pk=grade.pk))),
            ("Term statistics: average score in one term", (
                "SELECT avg(score) FROM grading_grade WHERE term_id = %s", (term.pk,))),
        )

        with connection.cursor() as cursor:
            cursor.execute("ANALYZE")
            cursor.execute("SHOW server_version")
            version = cursor.fetchone()[0].split()[0]
            cursor.execute(
                "SELECT count(*) FROM pg_inherits WHERE inhparent = 'grading_grade'::regclass"
            )
            partitions = cursor.fetchone()[0]

        out = [
            (f"PostgreSQL {version}, {Grade.objects.count():,} grades, "
             f"{f'{partitions} partitions' if partitions else 'not partitioned'}. "
             f"Medians of {runs} runs after {warmup} warm-up runs; term {term}, {offering.course.code} "
             f"({len(class_enrollments)} students)."),
            "",
            "| Query | Execution, ms | Planning, ms | Buffers |",
            "|---|---:|---:|---:|",
        ]
        plans = []
        for name, (sql, params) in queries:
            execution, planning = [], []
            for run in range(warmup + runs):
                with transaction.atomic(), connection.cursor() as cursor:
                    cursor.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, params)
                    plan = cursor.fetchone()[0]
                    plan = (json.loads(plan) if isinstance(plan, str) else plan)[0]
                if run >= warmup:
                    execution.append(plan["Execution Time"])
                    planning.append(plan["Planning Time"])
            buffers = plan["Plan"].get("Shared Hit Blocks", 0) + plan["Plan"].get("Shared Read Blocks", 0)
            out.append(f"| {name} | {statistics.median(execution):.3f} | {statistics.median(planning):.3f} | {buffers} |")
            with connection.cursor() as cursor:
                cursor.execute("EXPLAIN (COSTS OFF) " + sql, params)
                plans.append((name, "\n".join(row[0] for row in cursor.fetchall())))

        for name, plan in plans:
            out += ["", f"### {name}", "", "```", plan, "```"]
        self.stdout.write("\n".join(out))
