from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from grading.materialized_views import refresh_materialized_views
from grading.models import Grade


def schedule_refresh(using):
    transaction.on_commit(
        lambda: refresh_materialized_views(using=using),
        using=using,
    )


@receiver(post_save, sender=Grade)
def grade_saved(sender, instance, using, **kwargs):
    schedule_refresh(using)


@receiver(post_delete, sender=Grade)
def grade_deleted(sender, instance, using, **kwargs):
    schedule_refresh(using)