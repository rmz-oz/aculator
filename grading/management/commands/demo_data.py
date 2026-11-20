from django.core.management import call_command
from django.core.management.base import BaseCommand

from grading.demo import ensure_demo_accounts
from grading.models import Grade


class Command(BaseCommand):
    help = "Fake data plus the three demo accounts (#46). Runs on start when DEMO=1."

    def add_arguments(self, parser):
        parser.add_argument("--students", type=int, default=400, help="Passed to fake_data.")
        parser.add_argument(
            "--if-empty",
            action="store_true",
            help="Load fake data only when there are no grades, e.g. a restored backup is kept as it is.",
        )

    def handle(self, *args, **options):
        if options["if_empty"] and Grade.objects.exists():
            self.stdout.write("Grades exist, fake data not loaded.")
        else:
            call_command("fake_data", students=options["students"], stdout=self.stdout)
        ready = ensure_demo_accounts()
        self.stdout.write(self.style.SUCCESS(f"Demo accounts: {', '.join(ready)}."))
