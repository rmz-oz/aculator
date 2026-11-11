from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("grading", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE MATERIALIZED VIEW student_lo_scores AS
                SELECT
                    e.student_id,
                    e.offering_id,
                    lo.id AS learning_outcome_id,

                    SUM(g.score / a.max_score * 100 * alw.weight)
                    / SUM(alw.weight) AS score

                FROM grading_enrollment e

                JOIN grading_grade g
                    ON g.enrollment_id = e.id

                JOIN grading_assessment a
                    ON a.id = g.assessment_id
                    AND a.offering_id = e.offering_id
                    AND a.max_score > 0

                JOIN grading_assessmentloweight alw
                    ON alw.assessment_id = a.id

                JOIN grading_learningoutcome lo
                    ON lo.id = alw.learning_outcome_id
                    AND lo.offering_id = e.offering_id

                GROUP BY
                    e.student_id,
                    e.offering_id,
                    lo.id
                HAVING SUM(alw.weight) > 0;
            """,
            reverse_sql="""
                DROP MATERIALIZED VIEW IF EXISTS student_lo_scores;
            """,
        ),
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX student_lo_scores_unique
                ON student_lo_scores (
                    student_id,
                    offering_id,
                    learning_outcome_id
                );
            """,
            reverse_sql="""
                DROP INDEX IF EXISTS student_lo_scores_unique;
            """,
        ),
        migrations.RunSQL(
            sql="""
                CREATE MATERIALIZED VIEW course_po_scores AS
                SELECT
                    slo.student_id,
                    slo.offering_id,
                    lpw.program_outcome_id,
                    SUM(slo.score * lpw.weight)
                    / SUM(lpw.weight) AS score
                FROM student_lo_scores slo
                JOIN grading_lopoweight lpw
                    ON lpw.learning_outcome_id = slo.learning_outcome_id
                GROUP BY
                    slo.student_id,
                    slo.offering_id,
                    lpw.program_outcome_id
                HAVING SUM(lpw.weight) > 0;
            """,
            reverse_sql="""
                DROP MATERIALIZED VIEW IF EXISTS course_po_scores;
            """,
        ),
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX course_po_scores_unique
                ON course_po_scores (
                    student_id,
                    offering_id,
                    program_outcome_id
                );
            """,
            reverse_sql="""
                DROP INDEX IF EXISTS course_po_scores_unique;
            """,
        ),
        migrations.RunSQL(
            sql="""
                CREATE MATERIALIZED VIEW cross_course_po_scores AS
                -- Courses weighted by ECTS, decision 0004.
                SELECT
                    cpo.student_id,
                    cpo.program_outcome_id,
                    SUM(cpo.score * c.ects) / SUM(c.ects) AS score
                FROM course_po_scores cpo
                JOIN grading_courseoffering o ON o.id = cpo.offering_id
                JOIN grading_course c ON c.id = o.course_id
                GROUP BY
                    cpo.student_id,
                    cpo.program_outcome_id
                HAVING SUM(c.ects) > 0;
            """,
            reverse_sql="""
                DROP MATERIALIZED VIEW IF EXISTS cross_course_po_scores;
            """,
        ),
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX cross_course_po_scores_unique
                ON cross_course_po_scores (
                    student_id,
                    program_outcome_id
                );
            """,
            reverse_sql="""
                DROP INDEX IF EXISTS cross_course_po_scores_unique;
            """,
        ),
    ]
