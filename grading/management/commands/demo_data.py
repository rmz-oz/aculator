from django.core.management import call_command
from django.core.management.base import BaseCommand

from grading import demo_scenarios
from grading.demo import ensure_demo_accounts
from grading.models import Grade, GradeChange


class Command(BaseCommand):
    help = (
        "Fake data with the realistic mistakes of docs/demo_scenarios.md, plus the three demo accounts (#46, #100). "
        "Runs on start when DEMO=1."
    )

    def add_arguments(self, parser):
        parser.add_argument("--students", type=int, default=400, help="Passed to fake_data.")
        parser.add_argument("--seed", type=int, default=42, help="Passed to fake_data and the scenarios.")
        parser.add_argument(
            "--if-empty",
            action="store_true",
            help="Load data only when there are no grades, e.g. a restored backup is kept as it is.",
        )
        parser.add_argument("--clean", action="store_true", help="Fake data without the scenarios.")

    def handle(self, *args, **options):
        if options["if_empty"] and Grade.objects.exists():
            self.stdout.write("Grades exist, fake data not loaded.")
        elif demo_scenarios.applied():
            # fake_data again would put back the grades the scenarios removed.
            self.stdout.write("Demo scenarios already in, fake data not loaded again.")
        else:
            last = GradeChange.objects.order_by("-pk").values_list("pk", flat=True).first() or 0
            call_command("fake_data", students=options["students"], seed=options["seed"], stdout=self.stdout)
            if not options["clean"]:
                for scenario, where in demo_scenarios.apply(seed=options["seed"]):
                    self.stdout.write(f"{scenario}: {where}")
            # Loading is not a grade change. Without this the history would show
            # every scenario mistake as an edit away from the right score (#35).
            GradeChange.objects.filter(pk__gt=last).delete()
        ready = ensure_demo_accounts()
        self.stdout.write(self.style.SUCCESS(f"Demo accounts: {', '.join(ready)}."))
