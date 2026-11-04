import random
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from grading.models import (
    Term,
    Course,
    CourseOffering,
    LearningOutcome,
    ProgramOutcome,
    Assessment,
    Enrollment,
    Grade,
    AssessmentLOWeight,
    LOPOWeight,
)


class Command(BaseCommand):
    help = "Generate realistic fake academic data for testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--students",
            type=int,
            default=400,
            help="Number of fake students to generate.",
        )

    def handle(self, *args, **options):
        student_count = options["students"]

        self.stdout.write(
            f"Preparing to generate data for {student_count} students..."
        )
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

        self.stdout.write(
            self.style.SUCCESS(
                f"Created {created_students} fake students."
            )
        )
        terms = []

        for year in range(2023, 2027):
            for season in ["fall", "spring"]:
                term, created = Term.objects.get_or_create(
                    year=year,
                    season=season,
                )
                terms.append(term)

        self.stdout.write(
            self.style.SUCCESS(
                f"Created or retrieved {len(terms)} academic terms."
            )
        )
        course_data = [
            ("CSE101", "Introduction to Programming", 6),
            ("CSE102", "Object Oriented Programming", 6),
            ("CSE201", "Data Structures", 6),
            ("CSE202", "Algorithms", 6),
            ("CSE203", "Database Systems", 5),
            ("CSE301", "Software Engineering", 6),
            ("CSE302", "Operating Systems", 6),
            ("CSE303", "Computer Networks", 5),
        ]

        courses = []

        for code, name, ects in course_data:
            course, created = Course.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "ects": ects,
                },
            )
            courses.append(course)

        self.stdout.write(
            self.style.SUCCESS(
                f"Created or retrieved {len(courses)} courses."
            )
        )
        offerings = []

        for term in terms:
            for course in courses:
                offering, created = CourseOffering.objects.get_or_create(
                    course=course,
                    term=term,
                )
                offerings.append(offering)

        self.stdout.write(
            self.style.SUCCESS(
                f"Created or retrieved {len(offerings)} course offerings."
            )
        )
        students = list(
            User.objects.filter(
                username__startswith="fake_student_"
            ).order_by("id")[:student_count]
        )

       
        enrollments_to_create = []

        for student in students:
            random_generator = random.Random(student.username)

            selected_offerings = random_generator.sample(
                offerings,
                k=min(8, len(offerings))
            )

            for offering in selected_offerings:
                enrollments_to_create.append(
                    Enrollment(
                        student=student,
                        offering=offering,
                    )
                )

        Enrollment.objects.bulk_create(
            enrollments_to_create,
            ignore_conflicts=True,
            batch_size=1000,
        )

        enrollments = list(
            Enrollment.objects.filter(
                student__in=students,
                offering__in=offerings,
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Created or retrieved {len(enrollments)} enrollments."
            )
        )
        assessments = []

        assessment_data = [
            ("Midterm", 100),
            ("Final", 100),
            ("Quiz", 100),
            ("Project", 100),
        ]

        for offering in offerings:
            for name, max_score in assessment_data:
                assessment, created = Assessment.objects.get_or_create(
                    offering=offering,
                    name=name,
                    defaults={
                        "max_score": Decimal(max_score),
                    },
                )
                assessments.append(assessment)

        self.stdout.write(
            self.style.SUCCESS(
                f"Created or retrieved {len(assessments)} assessments."
            )
        )
        grades_to_create = []

        assessments_by_offering = {}

        for assessment in assessments:
            assessments_by_offering.setdefault(
                assessment.offering_id, []
            ).append(assessment)

        for enrollment in enrollments:
            offering_assessments = assessments_by_offering.get(
                enrollment.offering_id, []
            )

            for assessment in offering_assessments:
                score = Decimal(
                    str(random.randint(40, 100))
                )

                grades_to_create.append(
                    Grade(
                        enrollment=enrollment,
                        assessment=assessment,
                        score=score,
                    )
                )

        Grade.objects.bulk_create(
            grades_to_create,
            ignore_conflicts=True,
            batch_size=1000,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {len(grades_to_create)} fake grades."
            )
        )
        program_outcomes = []

        for i in range(1, 6):
            po, created = ProgramOutcome.objects.get_or_create(
                code=f"PO{i}",
                defaults={
                    "description": f"Program outcome {i}"
                },
            )
            program_outcomes.append(po)

        self.stdout.write(
            self.style.SUCCESS(
                f"Created or retrieved {len(program_outcomes)} program outcomes."
            )
        )
        learning_outcomes = []

        for offering in offerings:
            for i in range(1, 4):
                lo, created = LearningOutcome.objects.get_or_create(
                    offering=offering,
                    code=f"LO{i}",
                    defaults={
                        "description": f"Learning outcome {i}"
                    },
                )
                learning_outcomes.append(lo)

        self.stdout.write(
            self.style.SUCCESS(
                f"Created or retrieved {len(learning_outcomes)} learning outcomes."
            )
        )
        # Create Assessment-LO weights
        assessments_by_offering = {}

        for assessment in assessments:
            assessments_by_offering.setdefault(
                assessment.offering_id, []
            ).append(assessment)

        assessment_lo_weights = []

        for lo in learning_outcomes:
            related_assessments = assessments_by_offering.get(
                lo.offering_id, []
            )

            if not related_assessments:
                continue

            weight = Decimal("1") / Decimal(
                len(related_assessments)
            )

            for assessment in related_assessments:
                assessment_lo_weights.append(
                    AssessmentLOWeight(
                        assessment=assessment,
                        learning_outcome=lo,
                        weight=weight,
                    )
                )

        AssessmentLOWeight.objects.bulk_create(
            assessment_lo_weights,
            ignore_conflicts=True,
            batch_size=1000,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {len(assessment_lo_weights)} Assessment-LO weights."
            )
        )

        # Create LO-PO weights
        lo_po_weights = []

        for lo in learning_outcomes:
            selected_pos = random.sample(
                program_outcomes,
                k=min(3, len(program_outcomes))
            )

            for po in selected_pos:
                lo_po_weights.append(
                    LOPOWeight(
                        learning_outcome=lo,
                        program_outcome=po,
                        weight=random.randint(1, 5),
                    )
                )

        LOPOWeight.objects.bulk_create(
            lo_po_weights,
            ignore_conflicts=True,
            batch_size=1000,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {len(lo_po_weights)} LO-PO weights."
            )
        )