import random
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from grading.materialized_views import refresh_materialized_views
from grading.models import (
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

COURSES = [
    ("CSE101", "Introduction to Programming", 6),
    ("CSE102", "Object Oriented Programming", 6),
    ("CSE201", "Data Structures", 6),
    ("CSE202", "Algorithms", 6),
    ("CSE203", "Database Systems", 5),
    ("CSE301", "Software Engineering", 6),
    ("CSE302", "Operating Systems", 6),
    ("CSE303", "Computer Networks", 5),
]

ASSESSMENTS = [("Midterm", 100), ("Final", 100), ("Quiz", 20), ("Project", 100)]

# The department's 11 program outcomes (guidelines).
PROGRAM_OUTCOMES = 11
LOS_PER_OFFERING = 3
COURSES_PER_STUDENT = 6


class Command(BaseCommand):
    help = "Generate fake academic data. Same --seed gives the same data, reruns add nothing."

    def add_arguments(self, parser):
        parser.add_argument("--students", type=int, default=400, help="Number of fake students.")
        parser.add_argument("--seed", type=int, default=42, help="Random seed.")

    def rng(self, *key):
        # One generator per object, so adding students or courses does not
        # change the data that already exists.
        return random.Random(":".join(str(k) for k in (self.seed, *key)))

    @transaction.atomic
    def handle(self, *args, **options):
        self.seed = options["seed"]
        student_count = options["students"]
        User = get_user_model()

        created_students = 0
        for i in range(student_count):
            username = f"fake_student_{i + 1:04d}"
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": f"Student{i + 1}",
                    "last_name": "Demo",
                    "email": f"{username}@example.com",
                    "is_active": True,
                },
            )
            if created:
                user.set_unusable_password()
                user.save(update_fields=["password"])
                created_students += 1

        self.stdout.write(self.style.SUCCESS(f"Created {created_students} fake students."))

        terms = [
            Term.objects.get_or_create(year=year, season=season)[0]
            for year in range(2023, 2027)
            for season in ("fall", "spring")
        ]

        courses = [
            Course.objects.get_or_create(
                code=code,
                defaults={"name": name, "ects": ects},
            )[0]
            for code, name, ects in COURSES
        ]

        offerings = {
            (course.id, term.id): CourseOffering.objects.get_or_create(
                course=course,
                term=term,
            )[0]
            for term in terms
            for course in courses
        }

        self.stdout.write(
            self.style.SUCCESS(
                f"{len(terms)} terms, {len(courses)} courses, {len(offerings)} offerings."
            )
        )

        program_outcomes = [
            ProgramOutcome.objects.get_or_create(
                code=f"PO{i}",
                defaults={"description": f"Program outcome {i}"},
            )[0]
            for i in range(1, PROGRAM_OUTCOMES + 1)
        ]

        components = {
            po.pk: POComponent.objects.get_or_create(
                program_outcome=po,
                code="a",
                defaults={"description": po.description},
            )[0]
            for po in program_outcomes
        }

        assessments = {}  # offering id -> list of assessments
        learning_outcomes = []

        for offering in offerings.values():
            assessments[offering.id] = [
                Assessment.objects.get_or_create(
                    offering=offering,
                    name=name,
                    defaults={"max_score": Decimal(max_score)},
                )[0]
                for name, max_score in ASSESSMENTS
            ]

            for i in range(1, LOS_PER_OFFERING + 1):
                learning_outcomes.append(
                    LearningOutcome.objects.get_or_create(
                        offering=offering,
                        code=f"LO{i}",
                        defaults={"description": f"Learning outcome {i}"},
                    )[0]
                )

        # Each LO is measured by 2 of the 4 assessments with different weights,
        # so the LOs of one offering do not all get the same score.
        lo_weights = []
        lo_po_weights = []

        for lo in learning_outcomes:
            r = self.rng("lo", lo.offering_id, lo.code)

            for assessment in r.sample(assessments[lo.offering_id], k=2):
                weight = Decimal(r.choice(["0.3", "0.4", "0.5", "0.6", "0.7", "1.0"]))
                lo_weights.append(
                    AssessmentLOWeight(
                        assessment=assessment,
                        learning_outcome=lo,
                        weight=weight,
                    )
                )

            for po in r.sample(program_outcomes, k=r.randint(1, 3)):
                lo_po_weights.append(
                    LOPOWeight(
                        learning_outcome=lo,
                        component=components[po.pk],
                        weight=r.randint(1, 5),
                    )
                )

        AssessmentLOWeight.objects.bulk_create(
            lo_weights,
            ignore_conflicts=True,
            batch_size=1000,
        )
        LOPOWeight.objects.bulk_create(
            lo_po_weights,
            ignore_conflicts=True,
            batch_size=1000,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"{len(learning_outcomes)} LOs, {len(lo_po_weights)} LO-component weights."
            )
        )

        # Each student takes each chosen course once, in one term, and has a
        # base level so there are strong and weak students.
        students = list(
            User.objects.filter(
                username__startswith="fake_student_",
            ).order_by("username")[:student_count]
        )

        enrollments = []
        for student in students:
            r = self.rng("student", student.username)

            for course in r.sample(courses, k=min(COURSES_PER_STUDENT, len(courses))):
                term = r.choice(terms)
                enrollments.append(
                    Enrollment(
                        student=student,
                        offering=offerings[(course.id, term.id)],
                    )
                )

        Enrollment.objects.bulk_create(
            enrollments,
            ignore_conflicts=True,
            batch_size=1000,
        )
        enrollments = Enrollment.objects.filter(
            student__in=students,
        ).select_related("student")

        grades = []
        for enrollment in enrollments:
            student_r = self.rng("student", enrollment.student.username, "level")
            level = min(max(student_r.gauss(70, 12), 25), 98)
            r = self.rng("grade", enrollment.student.username, enrollment.offering_id)

            for assessment in assessments[enrollment.offering_id]:
                percent = min(max(r.gauss(level, 8), 0), 100)
                score = (
                    assessment.max_score
                    * Decimal(str(round(percent, 1)))
                    / 100
                ).quantize(Decimal("0.01"))

                grades.append(
                    Grade(
                        enrollment=enrollment,
                        assessment=assessment,
                        score=score,
                    )
                )

        Grade.objects.bulk_create(
            grades,
            ignore_conflicts=True,
            batch_size=1000,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"{len(enrollments)} enrollments, {len(grades)} grades."
            )
        )

        refresh_materialized_views()
        self.stdout.write(
            self.style.SUCCESS("Materialized views refreshed successfully!")
        )
