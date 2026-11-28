"""Retakes and makeup exams (#104, #105, decision 0011).

A course taken twice counts once in the cross-course scores: the latest
attempt that has scores, as the regulation counts the last grade. Both
attempts keep their per-offering rows, so the profile shows both.

An assessment can replace another one of the same offering (a makeup
replaces the final). For a student with a graded makeup the replaced
assessment is left out; without one it counts as before. A makeup the
student is marked absent from is no attempt: it is left out and the replaced
assessment stays.
"""

from django.db import migrations, models
import django.db.models.deletion

SEASON_ORDER = """
CREATE FUNCTION term_season_order(season text) RETURNS int
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE season WHEN 'spring' THEN 1 WHEN 'summer' THEN 2 WHEN 'fall' THEN 3 END
$$;
"""

REFRESH = """
CREATE OR REPLACE FUNCTION refresh_scores(p_offerings bigint[], p_students bigint[] DEFAULT '{}')
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    v_terms bigint[];
    v_students bigint[];
BEGIN
    -- One at a time across all connections: two refreshes sharing a student
    -- would both delete and insert that student's cross-course rows. Released
    -- at the end of the transaction.
    PERFORM pg_advisory_xact_lock(hashtext('grading.refresh_scores'));

    -- Naming the terms lets PostgreSQL read only their grade partitions (#33).
    SELECT array_agg(DISTINCT term_id) INTO v_terms
    FROM grading_courseoffering WHERE id = ANY(p_offerings);

    DELETE FROM student_lo_scores WHERE offering_id = ANY(p_offerings);
    INSERT INTO student_lo_scores
    SELECT e.student_id, e.offering_id, lo.id,
           sum(g.score / a.max_score * 100 * alw.weight) / sum(alw.weight)
    FROM grading_enrollment e
    JOIN grading_grade g ON g.enrollment_id = e.id AND g.term_id = ANY(v_terms)
    JOIN grading_assessment a ON a.id = g.assessment_id
         AND a.offering_id = e.offering_id AND a.max_score > 0
    -- A makeup the student was absent from is no attempt: left out (#105).
         AND NOT (a.replaces_id IS NOT NULL AND g.status = 'absent')
    -- A graded makeup replaces the assessment it names for this student.
         AND NOT EXISTS (
             SELECT 1 FROM grading_assessment r
             JOIN grading_grade rg ON rg.assessment_id = r.id AND rg.enrollment_id = e.id
                  AND rg.term_id = ANY(v_terms) AND rg.status = 'graded'
             WHERE r.replaces_id = a.id AND r.offering_id = a.offering_id
         )
    JOIN grading_assessmentloweight alw ON alw.assessment_id = a.id
    JOIN grading_learningoutcome lo ON lo.id = alw.learning_outcome_id
         AND lo.offering_id = e.offering_id
    WHERE e.offering_id = ANY(p_offerings)
    GROUP BY e.student_id, e.offering_id, lo.id
    HAVING sum(alw.weight) > 0;

    DELETE FROM student_component_scores WHERE offering_id = ANY(p_offerings);
    INSERT INTO student_component_scores
    SELECT slo.student_id, slo.offering_id, pc.program_outcome_id, pc.id,
           sum(slo.score * lpw.weight::numeric) / sum(lpw.weight)::numeric
    FROM student_lo_scores slo
    JOIN grading_lopoweight lpw ON lpw.learning_outcome_id = slo.learning_outcome_id
    JOIN grading_pocomponent pc ON pc.id = lpw.component_id
    WHERE slo.offering_id = ANY(p_offerings)
    GROUP BY slo.student_id, slo.offering_id, pc.program_outcome_id, pc.id
    HAVING sum(lpw.weight) > 0;

    SELECT array_agg(DISTINCT s) INTO v_students FROM (
        SELECT student_id FROM grading_enrollment WHERE offering_id = ANY(p_offerings)
        UNION SELECT unnest(p_students)
    ) x(s);

    DELETE FROM cross_course_po_scores WHERE student_id = ANY(v_students);
    INSERT INTO cross_course_po_scores
    SELECT student_id, program_outcome_id, avg(score)
    FROM (
        SELECT cs.student_id, cs.program_outcome_id, cs.component_id,
               sum(cs.score * o.ects::numeric) / sum(o.ects)::numeric AS score
        FROM student_component_scores cs
        JOIN grading_courseoffering o ON o.id = cs.offering_id
        JOIN grading_term t ON t.id = o.term_id
        WHERE cs.student_id = ANY(v_students)
          -- A retaken course counts once: its latest attempt with scores (#104).
          AND NOT EXISTS (
              SELECT 1 FROM student_component_scores cs2
              JOIN grading_courseoffering o2 ON o2.id = cs2.offering_id
              JOIN grading_term t2 ON t2.id = o2.term_id
              WHERE cs2.student_id = cs.student_id AND o2.course_id = o.course_id
                AND (t2.year, term_season_order(t2.season), o2.id)
                    > (t.year, term_season_order(t.season), o.id)
          )
        GROUP BY cs.student_id, cs.program_outcome_id, cs.component_id
        HAVING sum(o.ects) > 0
    ) sc
    GROUP BY student_id, program_outcome_id;

    REFRESH MATERIALIZED VIEW CONCURRENTLY department_po_means;
END $$;

SELECT refresh_all_scores();
"""

PREVIOUS = """
CREATE OR REPLACE FUNCTION refresh_scores(p_offerings bigint[], p_students bigint[] DEFAULT '{}')
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    v_terms bigint[];
    v_students bigint[];
BEGIN
    -- One at a time across all connections: two refreshes sharing a student
    -- would both delete and insert that student's cross-course rows. Released
    -- at the end of the transaction.
    PERFORM pg_advisory_xact_lock(hashtext('grading.refresh_scores'));

    -- Naming the terms lets PostgreSQL read only their grade partitions (#33).
    SELECT array_agg(DISTINCT term_id) INTO v_terms
    FROM grading_courseoffering WHERE id = ANY(p_offerings);

    DELETE FROM student_lo_scores WHERE offering_id = ANY(p_offerings);
    INSERT INTO student_lo_scores
    SELECT e.student_id, e.offering_id, lo.id,
           sum(g.score / a.max_score * 100 * alw.weight) / sum(alw.weight)
    FROM grading_enrollment e
    JOIN grading_grade g ON g.enrollment_id = e.id AND g.term_id = ANY(v_terms)
    JOIN grading_assessment a ON a.id = g.assessment_id
         AND a.offering_id = e.offering_id AND a.max_score > 0
    JOIN grading_assessmentloweight alw ON alw.assessment_id = a.id
    JOIN grading_learningoutcome lo ON lo.id = alw.learning_outcome_id
         AND lo.offering_id = e.offering_id
    WHERE e.offering_id = ANY(p_offerings)
    GROUP BY e.student_id, e.offering_id, lo.id
    HAVING sum(alw.weight) > 0;

    DELETE FROM student_component_scores WHERE offering_id = ANY(p_offerings);
    INSERT INTO student_component_scores
    SELECT slo.student_id, slo.offering_id, pc.program_outcome_id, pc.id,
           sum(slo.score * lpw.weight::numeric) / sum(lpw.weight)::numeric
    FROM student_lo_scores slo
    JOIN grading_lopoweight lpw ON lpw.learning_outcome_id = slo.learning_outcome_id
    JOIN grading_pocomponent pc ON pc.id = lpw.component_id
    WHERE slo.offering_id = ANY(p_offerings)
    GROUP BY slo.student_id, slo.offering_id, pc.program_outcome_id, pc.id
    HAVING sum(lpw.weight) > 0;

    SELECT array_agg(DISTINCT s) INTO v_students FROM (
        SELECT student_id FROM grading_enrollment WHERE offering_id = ANY(p_offerings)
        UNION SELECT unnest(p_students)
    ) x(s);

    DELETE FROM cross_course_po_scores WHERE student_id = ANY(v_students);
    INSERT INTO cross_course_po_scores
    SELECT student_id, program_outcome_id, avg(score)
    FROM (
        SELECT cs.student_id, cs.program_outcome_id, cs.component_id,
               sum(cs.score * o.ects::numeric) / sum(o.ects)::numeric AS score
        FROM student_component_scores cs
        JOIN grading_courseoffering o ON o.id = cs.offering_id
        WHERE cs.student_id = ANY(v_students)
        GROUP BY cs.student_id, cs.program_outcome_id, cs.component_id
        HAVING sum(o.ects) > 0
    ) sc
    GROUP BY student_id, program_outcome_id;

    REFRESH MATERIALIZED VIEW CONCURRENTLY department_po_means;
END $$;

DROP FUNCTION term_season_order(text);

SELECT refresh_all_scores();
"""


class Migration(migrations.Migration):
    dependencies = [("grading", "0013_score_tables")]

    operations = [
        migrations.AddField(
            model_name="assessment",
            name="replaces",
            field=models.OneToOneField(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="replaced_by", to="grading.assessment",
                help_text="For a makeup: the assessment it replaces for the students who take it.",
            ),
        ),
        migrations.AddConstraint(
            model_name="assessment",
            constraint=models.CheckConstraint(
                condition=~models.Q(replaces=models.F("pk")), name="assessment_not_replacing_itself",
            ),
        ),
        migrations.RunSQL(sql=SEASON_ORDER + REFRESH, reverse_sql=PREVIOUS),
    ]
