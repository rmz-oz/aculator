from django.db import migrations


DROP_VIEW = "DROP MATERIALIZED VIEW cross_course_po_scores;"

CREATE_VIEW = """
CREATE MATERIALIZED VIEW cross_course_po_scores AS
WITH component_scores AS (
    SELECT
        slo.student_id,
        slo.offering_id,
        pc.program_outcome_id,
        pc.id AS component_id,
        SUM(slo.score * lpw.weight) / SUM(lpw.weight) AS score
    FROM student_lo_scores slo
    JOIN grading_lopoweight lpw
        ON lpw.learning_outcome_id = slo.learning_outcome_id
    JOIN grading_pocomponent pc
        ON pc.id = lpw.component_id
    GROUP BY
        slo.student_id,
        slo.offering_id,
        pc.program_outcome_id,
        pc.id
    HAVING SUM(lpw.weight) > 0
),
student_components AS (
    SELECT
        cs.student_id,
        cs.program_outcome_id,
        cs.component_id,
        SUM(cs.score * o.ects) / SUM(o.ects) AS score
    FROM component_scores cs
    JOIN grading_courseoffering o ON o.id = cs.offering_id
    GROUP BY
        cs.student_id,
        cs.program_outcome_id,
        cs.component_id
    HAVING SUM(o.ects) > 0
)
SELECT
    student_id,
    program_outcome_id,
    AVG(score) AS score
FROM student_components
GROUP BY student_id, program_outcome_id;

CREATE UNIQUE INDEX cross_course_po_scores_unique
ON cross_course_po_scores (student_id, program_outcome_id);
"""

# Rolling back restores the catalog-based calculation.
CREATE_PREVIOUS_VIEW = CREATE_VIEW.replace("o.ects", "c.ects").replace(
    "JOIN grading_courseoffering o ON o.id = cs.offering_id",
    "JOIN grading_courseoffering o ON o.id = cs.offering_id\n"
    "    JOIN grading_course c ON c.id = o.course_id",
)


class Migration(migrations.Migration):
    dependencies = [
        ("grading", "0007_offering_ects"),
    ]

    operations = [
        migrations.RunSQL(
            sql=f"{DROP_VIEW}\n{CREATE_VIEW}",
            reverse_sql=f"{DROP_VIEW}\n{CREATE_PREVIOUS_VIEW}",
        ),
    ]
