from functools import partial

from django.db import connections, transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from grading.materialized_views import refresh_materialized_views
from grading.models import Grade


def schedule_refresh(using):
    """Refresh the views once after the transaction commits, however many grades changed.

    A rolled back transaction drops its callbacks, so nothing is left behind.
    """
    pending = connections[using].run_on_commit
    if any(getattr(func, "func", None) is refresh_materialized_views for _, func, _ in pending):
        return
    transaction.on_commit(partial(refresh_materialized_views, using=using), using=using)


@receiver(post_save, sender=Grade)
def grade_saved(sender, instance, using, **kwargs):
    schedule_refresh(using)


@receiver(post_delete, sender=Grade)
def grade_deleted(sender, instance, using, **kwargs):
    schedule_refresh(using)
