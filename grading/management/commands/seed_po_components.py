from django.core.management.base import BaseCommand
from django.db import transaction

from grading.models import POComponent, ProgramOutcome

COMPONENTS = {
    "PO1": (
        ("a", "Math and science knowledge"),
        ("b", "Engineering knowledge"),
        ("c", "Applying them to complex problems"),
    ),
    "PO2": (
        ("a", "Identify and formulate"),
        ("b", "Analyse and solve"),
    ),
    "PO3": (
        ("a", "Design to requirements"),
        ("b", "Realistic constraints"),
    ),
    "PO4": (
        ("a", "Select modern techniques and tools"),
        ("b", "Use them"),
    ),
    "PO5": (
        ("a", "Design and run experiments"),
        ("b", "Analyse and interpret data"),
    ),
    "PO6": (
        ("a", "Individual work"),
        ("b", "Teamwork within the discipline"),
        ("c", "Multidisciplinary teamwork"),
    ),
    "PO7": (
        ("a", "Oral"),
        ("b", "Written"),
    ),
    "PO8": (
        ("a", "Independent learning"),
        ("b", "Adapting to new technology"),
    ),
    "PO9": (
        ("a", "Ethics and professional responsibility"),
    ),
    "PO10": (
        ("a", "Project management"),
        ("b", "Risk and change management"),
        ("c", "Entrepreneurship"),
    ),
    "PO11": (
        ("a", "Health and safety"),
        ("b", "Environment"),
        ("c", "Legal implications"),
    ),
}


class Command(BaseCommand):
    help = "Add the department's starting PO components without overwriting edits."

    @transaction.atomic
    def handle(self, *args, **options):
        created_count = 0

        for po_code, definitions in COMPONENTS.items():
            po = ProgramOutcome.objects.filter(code=po_code).first()

            if po is None:
                self.stdout.write(
                    self.style.WARNING(f"Skipped missing {po_code}.")
                )
                continue

            for code, description in definitions:
                _, created = POComponent.objects.get_or_create(
                    program_outcome=po,
                    code=code,
                    defaults={"description": description},
                )
                created_count += int(created)

        self.stdout.write(
            self.style.SUCCESS(f"Created {created_count} components.")
        )