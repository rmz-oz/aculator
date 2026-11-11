from django.core.management.base import BaseCommand

from grading.materialized_views import (
    MATERIALIZED_VIEWS,
    refresh_materialized_views,
)


class Command(BaseCommand):
    help = "Refresh all materialized views in dependency order."

    def handle(self, *args, **options):
        refresh_materialized_views()

        for view_name in MATERIALIZED_VIEWS:
            self.stdout.write(
                self.style.SUCCESS(f"Refreshed {view_name}")
            )

        self.stdout.write(
            self.style.SUCCESS(
                "All materialized views refreshed successfully!"
            )
        )
