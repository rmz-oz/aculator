"""The score tables and the department view (migration 0013, #79).

student_lo_scores, student_component_scores and cross_course_po_scores are
tables kept up to date per offering by the SQL function refresh_scores();
course_po_scores is a plain view over them. department_po_means is the one
materialized view, refreshed at the end of every refresh_scores() call.
"""

from django.db import connections, transaction

SCORE_TABLES = (
    "student_lo_scores",
    "student_component_scores",
    "cross_course_po_scores",
    "department_po_means",
)


def refresh_scores(offerings, students=(), using="default"):
    """Recompute these offerings and the cross-course rows of their students.

    `students` adds students who are no longer enrolled in any of them, for
    example after an enrollment was deleted. Runs in its own transaction:
    inside the SERIALIZABLE grade import it would make imports of different
    courses that share students fail with a serialization error.
    """
    with transaction.atomic(using=using), connections[using].cursor() as cursor:
        cursor.execute(
            "SELECT refresh_scores(%s::bigint[], %s::bigint[])",
            [sorted(offerings), sorted(students)],
        )


def refresh_materialized_views(using="default"):
    """Recompute every score from scratch.

    For writes that send no signal (bulk_create, QuerySet.update, a restored
    backup) and for `manage.py refresh_materialized_views`.
    """
    with transaction.atomic(using=using), connections[using].cursor() as cursor:
        cursor.execute("SELECT refresh_all_scores()")
