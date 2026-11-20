from django.db import connections, transaction
from django.db.models.signals import post_delete, post_save

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
)

# Everything the score views are computed from. A grade changes often; the
# others rarely (a weight, ECTS or max score edit in the admin), but without
# a refresh the department average on the student profile would stay stale.
SCORE_INPUTS = (
    Grade,
    Assessment,
    AssessmentLOWeight,
    Course,
    CourseOffering,
    Enrollment,
    LearningOutcome,
    LOPOWeight,
    POComponent,
)


def schedule_refresh(using):
    """Refresh the views once after the transaction commits, however many grades changed.

    A rolled back transaction drops its callbacks, so nothing is left behind.
    """
    pending = connections[using].run_on_commit
    if any(getattr(func, "refreshes_views", False) for _, func, _ in pending):
        return

    # A named function, not functools.partial: robust=True logs a failure by
    # the callback's __qualname__, which a partial does not have.
    def refresh_score_views():
        refresh_materialized_views(using=using)

    refresh_score_views.refreshes_views = True
    # robust: the data is already committed when this runs. A failed refresh
    # is logged and the views catch up on the next change or with
    # `manage.py refresh_materialized_views`; the user still gets their page (#102).
    transaction.on_commit(refresh_score_views, using=using, robust=True)


def score_input_changed(sender, instance, using, **kwargs):
    schedule_refresh(using)


for model in SCORE_INPUTS:
    post_save.connect(score_input_changed, sender=model, dispatch_uid=f"refresh-after-save-{model.__name__}")
    post_delete.connect(score_input_changed, sender=model, dispatch_uid=f"refresh-after-delete-{model.__name__}")
