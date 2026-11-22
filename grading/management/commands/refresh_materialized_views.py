from django.core.management.base import BaseCommand

from grading.materialized_views import SCORE_TABLES, refresh_materialized_views


class Command(BaseCommand):
    help = "Recompute every score table and the department view from scratch."

    def handle(self, *args, **options):
        refresh_materialized_views()
        self.stdout.write(self.style.SUCCESS(f"Recomputed {', '.join(SCORE_TABLES)}"))
