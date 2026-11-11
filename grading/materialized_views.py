from django.db import connections

MATERIALIZED_VIEWS = (
    "student_lo_scores",
    "course_po_scores",
    "cross_course_po_scores",
)


def refresh_materialized_views(using="default"):
    connection = connections[using]

    for view_name in MATERIALIZED_VIEWS:
        with connection.cursor() as cursor:
            cursor.execute(
                f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view_name};"
            )