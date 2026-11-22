from django.db import connections, transaction
from django.db.models.signals import post_delete, post_init, post_save

from grading.materialized_views import refresh_materialized_views, refresh_scores
from grading.models import (
    Assessment,
    AssessmentLOWeight,
    CourseOffering,
    Enrollment,
    Grade,
    LearningOutcome,
    LOPOWeight,
    POComponent,
)

# What each score input points at. An offering is recomputed when anything
# in it changes; assessments and LOs are turned into their offerings after
# the commit, in one query each. A changed foreign key counts with both its
# old and its new value, so moving a row recomputes both offerings.
TRACKED = {
    Grade: {"assessment_id": "assessments"},
    Assessment: {"offering_id": "offerings"},
    AssessmentLOWeight: {"assessment_id": "assessments", "learning_outcome_id": "los"},
    LearningOutcome: {"offering_id": "offerings"},
    LOPOWeight: {"learning_outcome_id": "los"},
    Enrollment: {"offering_id": "offerings", "student_id": "students"},
    CourseOffering: {"id": "offerings"},
}
# A component belongs to a PO, not to an offering: recompute everything.
# Rare, an admin edit. Course is not here: since 0008 the scores read the
# offering's own ECTS, nothing of the course.
EVERYTHING = (POComponent,)


class ScoreChanges:
    def __init__(self):
        self.offerings, self.assessments, self.los, self.students = set(), set(), set(), set()
        self.everything = False


def _changes(using):
    """The changes of the current transaction, with the refresh queued once after its commit.

    A rolled back transaction drops its callbacks and with them its changes.
    """
    for _, func, _ in connections[using].run_on_commit:
        changes = getattr(func, "score_changes", None)
        if changes is not None:
            return changes, False
    return ScoreChanges(), True


def _queue(changes, using):
    # A named function, not functools.partial: robust=True logs a failure by
    # the callback's __qualname__, which a partial does not have.
    def refresh_score_tables():
        apply_changes(changes, using)

    refresh_score_tables.score_changes = changes
    # robust: the data is already committed when this runs. A failed refresh
    # is logged and the user still gets their page (#102); the next change to
    # the same offering or `manage.py refresh_materialized_views` repairs it.
    transaction.on_commit(refresh_score_tables, using=using, robust=True)


def apply_changes(changes, using):
    if changes.everything:
        refresh_materialized_views(using=using)
        return
    offerings = set(changes.offerings)
    with connections[using].cursor() as cursor:
        # Rows deleted in the same transaction are gone; their offering came
        # with the parent's own signal (an assessment's or LO's delete).
        for ids, table in ((changes.assessments, "grading_assessment"), (changes.los, "grading_learningoutcome")):
            if ids:
                cursor.execute(f"SELECT DISTINCT offering_id FROM {table} WHERE id = ANY(%s)", [list(ids)])
                offerings.update(row[0] for row in cursor.fetchall())
    if offerings or changes.students:
        refresh_scores(offerings, changes.students, using=using)


def record(instance, using, old=None):
    changes, new = _changes(using)
    if type(instance) in EVERYTHING:
        changes.everything = True
    else:
        for field, kind in TRACKED[type(instance)].items():
            values = getattr(changes, kind)
            value = getattr(instance, field)
            if value is not None:
                values.add(value)
            if old and old.get(field) is not None:
                values.add(old[field])
    # Queued after recording: outside a transaction on_commit runs at once.
    if new:
        _queue(changes, using)


def remember_loaded_values(sender, instance, **kwargs):
    # Read from __dict__, not getattr: a deferred field would cost a query.
    instance._score_loaded = {f: instance.__dict__.get(f) for f in TRACKED[sender]}


def score_input_saved(sender, instance, using, created, **kwargs):
    old = None if created else getattr(instance, "_score_loaded", None)
    record(instance, using, old)
    if sender in TRACKED:
        remember_loaded_values(sender, instance)


def score_input_deleted(sender, instance, using, **kwargs):
    record(instance, using, getattr(instance, "_score_loaded", None))


for model in (*TRACKED, *EVERYTHING):
    post_save.connect(score_input_saved, sender=model, dispatch_uid=f"scores-after-save-{model.__name__}")
    post_delete.connect(score_input_deleted, sender=model, dispatch_uid=f"scores-after-delete-{model.__name__}")
for model in TRACKED:
    post_init.connect(remember_loaded_values, sender=model, dispatch_uid=f"scores-loaded-{model.__name__}")
