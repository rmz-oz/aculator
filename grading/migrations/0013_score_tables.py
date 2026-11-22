"""Score tables kept up to date per offering instead of fully refreshed views (#79).

Refreshing the three materialized views after every change recomputed every
grade in the database inside the request: 0.27 s at 400 students, about 4 s
at 4000, growing with the whole database. They become tables with the same
names and columns, and refresh_scores() recomputes only the offerings that
changed and the cross-course rows of their students. course_po_scores is a
plain view over the component scores, so its readers do not change.

The department mean per PO stays a materialized view, department_po_means:
one row per PO, refreshed concurrently in a few milliseconds.

Same SQL as the views, so the numbers are exactly equal (test_materialized_views).
"""

from django.db import migrations

DROP_VIEWS = """
DROP MATERIALIZED VIEW cross_course_po_scores;
DROP MATERIALIZED VIEW course_po_scores;
DROP MATERIALIZED VIEW student_lo_scores;
"""

CREATE = """
CREATE TABLE student_lo_scores (
    student_id bigint NOT NULL,
    offering_id bigint NOT NULL,
    learning_outcome_id bigint NOT NULL,
    score numeric NOT NULL,
    PRIMARY KEY (offering_id, student_id, learning_outcome_id)
);

CREATE TABLE student_component_scores (
    student_id bigint NOT NULL,
    offering_id bigint NOT NULL,
    program_outcome_id bigint NOT NULL,
    component_id bigint NOT NULL,
    score numeric NOT NULL,
    PRIMARY KEY (offering_id, student_id, component_id)
);
-- The cross-course step reads a student's components from every offering.
CREATE INDEX student_component_scores_student ON student_component_scores (student_id);

CREATE TABLE cross_course_po_scores (
    student_id bigint NOT NULL,
    program_outcome_id bigint NOT NULL,
    score numeric NOT NULL,
    PRIMARY KEY (student_id, program_outcome_id)
);

CREATE VIEW course_po_scores AS
SELECT student_id, offering_id, program_outcome_id, avg(score) AS score
FROM student_component_scores
GROUP BY student_id, offering_id, program_outcome_id;

CREATE MATERIALIZED VIEW department_po_means AS
SELECT program_outcome_id, avg(score) AS score, count(*) AS students
FROM cross_course_po_scores
GROUP BY program_outcome_id;
CREATE UNIQUE INDEX department_po_means_unique ON department_po_means (program_outcome_id);

-- Recompute the score rows of these offerings, then the cross-course rows of
-- everyone enrolled in them and of p_students (students who left them).
CREATE FUNCTION refresh_scores(p_offerings bigint[], p_students bigint[] DEFAULT '{}')
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

-- Everything from scratch: after bulk writes that send no signal
-- (fake_data, demo data, a restored backup) and when a PO component changes.
CREATE FUNCTION refresh_all_scores() RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('grading.refresh_scores'));
    -- Rows of offerings that no longer exist.
    DELETE FROM student_lo_scores s
    WHERE NOT EXISTS (SELECT 1 FROM grading_courseoffering o WHERE o.id = s.offering_id);
    DELETE FROM student_component_scores s
    WHERE NOT EXISTS (SELECT 1 FROM grading_courseoffering o WHERE o.id = s.offering_id);
    PERFORM refresh_scores(
        ARRAY(SELECT id FROM grading_courseoffering),
        ARRAY(SELECT DISTINCT student_id FROM cross_course_po_scores)
    );
END $$;

SELECT refresh_all_scores();
"""

DROP = """
DROP FUNCTION refresh_all_scores();
DROP FUNCTION refresh_scores(bigint[], bigint[]);
DROP MATERIALIZED VIEW department_po_means;
DROP VIEW course_po_scores;
DROP TABLE cross_course_po_scores;
DROP TABLE student_component_scores;
DROP TABLE student_lo_scores;
"""

# The views as 0012 left them, for going back.
PREVIOUS_VIEWS = """
CREATE MATERIALIZED VIEW student_lo_scores AS
SELECT e.student_id, e.offering_id, lo.id AS learning_outcome_id,
       sum(g.score / a.max_score * 100::numeric * alw.weight) / sum(alw.weight) AS score
FROM grading_enrollment e
JOIN grading_grade g ON g.enrollment_id = e.id
JOIN grading_assessment a ON a.id = g.assessment_id AND a.offering_id = e.offering_id AND a.max_score > 0::numeric
JOIN grading_assessmentloweight alw ON alw.assessment_id = a.id
JOIN grading_learningoutcome lo ON lo.id = alw.learning_outcome_id AND lo.offering_id = e.offering_id
GROUP BY e.student_id, e.offering_id, lo.id
HAVING sum(alw.weight) > 0::numeric;
CREATE UNIQUE INDEX student_lo_scores_unique ON student_lo_scores (student_id, offering_id, learning_outcome_id);

CREATE MATERIALIZED VIEW course_po_scores AS
WITH component_scores AS (
    SELECT slo.student_id, slo.offering_id, pc.program_outcome_id, pc.id AS component_id,
           sum(slo.score * lpw.weight::numeric) / sum(lpw.weight)::numeric AS score
    FROM student_lo_scores slo
    JOIN grading_lopoweight lpw ON lpw.learning_outcome_id = slo.learning_outcome_id
    JOIN grading_pocomponent pc ON pc.id = lpw.component_id
    GROUP BY slo.student_id, slo.offering_id, pc.program_outcome_id, pc.id
    HAVING sum(lpw.weight) > 0
)
SELECT student_id, offering_id, program_outcome_id, avg(score) AS score
FROM component_scores
GROUP BY student_id, offering_id, program_outcome_id;
CREATE UNIQUE INDEX course_po_scores_unique ON course_po_scores (student_id, offering_id, program_outcome_id);

CREATE MATERIALIZED VIEW cross_course_po_scores AS
WITH component_scores AS (
    SELECT slo.student_id, slo.offering_id, pc.program_outcome_id, pc.id AS component_id,
           sum(slo.score * lpw.weight::numeric) / sum(lpw.weight)::numeric AS score
    FROM student_lo_scores slo
    JOIN grading_lopoweight lpw ON lpw.learning_outcome_id = slo.learning_outcome_id
    JOIN grading_pocomponent pc ON pc.id = lpw.component_id
    GROUP BY slo.student_id, slo.offering_id, pc.program_outcome_id, pc.id
    HAVING sum(lpw.weight) > 0
), student_components AS (
    SELECT cs.student_id, cs.program_outcome_id, cs.component_id,
           sum(cs.score * o.ects::numeric) / sum(o.ects)::numeric AS score
    FROM component_scores cs
    JOIN grading_courseoffering o ON o.id = cs.offering_id
    GROUP BY cs.student_id, cs.program_outcome_id, cs.component_id
    HAVING sum(o.ects) > 0
)
SELECT student_id, program_outcome_id, avg(score) AS score
FROM student_components
GROUP BY student_id, program_outcome_id;
CREATE UNIQUE INDEX cross_course_po_scores_unique ON cross_course_po_scores (student_id, program_outcome_id);
"""


class Migration(migrations.Migration):
    dependencies = [("grading", "0012_partition_grades_by_term")]

    operations = [
        migrations.RunSQL(
            sql=DROP_VIEWS + CREATE,
            reverse_sql=DROP + PREVIOUS_VIEWS,
        ),
    ]
