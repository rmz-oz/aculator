# Grades partitioned by term

Grades are the largest table, and a class report or a grade import only ever needs one term. Since #33 `grading_grade`
is partitioned by `LIST (term_id)`: one partition per term, created when the term is added and dropped when it is
deleted, and a DEFAULT partition that stays empty.

## How it is built

In two deploys, so the version still running during a deploy can always save grades
([failures.md](failures.md#partitioning-the-grades-33)):

1. `0011_grade_term` adds `term_id` to grades, possibly empty, fills it in without writing grade history (#35), and
   the code sets it on every save.
2. `0012_partition_grades_by_term`, in one transaction:
   - copies every grade into a new partitioned table, taking the term from the grade's offering (this also covers
     rows an older version saved without one), and checks that count, sum of ids and sum of scores are unchanged;
   - continues ids after the highest ever handed out, so a deleted grade's id, still in its history, is not reused;
   - keeps the primary key as `(id, term_id)` and the one-grade-per-student rule as `(enrollment, assessment, term)`,
     because PostgreSQL wants the partition key in both. The term follows from the enrollment, so the rule is the same;
   - adds triggers that refuse a grade whose term is not its offering's, and refuse moving an offering, enrollment or
     assessment that has grades. A grade never changes term;
   - recreates the three score views from their current definitions and runs `ANALYZE`.

0012 cannot be reversed. On 480,000 grades 0011 took 13 s and 0012 took 14 s. 0012 takes all its locks at once,
with a short timeout and another try, so it cannot deadlock with a grade import that is running.

## What it changes in the app

PostgreSQL only skips partitions when the query names the term. So the grade queries do (`grading/services.py`,
`grading/explain.py`, `Assessment.term_grades()`), and saving a grade updates `WHERE id = ... AND term_id = ...`
(`Grade._do_update`). Without the term every partition is planned and locked: saving one class's 1,551 grades by id
alone took about three times as long.

## Measurements

480,000 grades from `fake_data --years 10 --students 20000`: 8 courses, each student takes 6 of them, 20 terms with
6,000 to 50,000 grades each. The measured class is CSE101 in 2032 Spring, 1,551 students, in the largest term (50,040
grades). PostgreSQL 15.17 on an otherwise idle laptop. The plain copy has the same rows and what the table had before
#33 (primary key, unique rule, foreign keys, indexes on enrollment and assessment, the history trigger) plus an index on
`term_id`. Medians of 15 runs after 3 warm-up runs from `python manage.py benchmark_partition`, two rounds each.

| Query | Plain, ms | Partitioned, ms |
|---|---:|---:|
| Class report: grades of one offering | 24.5 + 1.5 planning | 7.1 to 7.6 + 1.8 planning |
| Student profile: one student's grades, every term | 0.06 + 0.6 | 0.07 + 0.7 |
| Grade import: grades of one assessment | 0.54 | 0.66 |
| Saving one grade: find it by enrollment, assessment and term | 0.006 | 0.005 |
| Admin: one grade by id, no term known | 0.005 | 0.05 + 0.5 planning |
| Average score in one term | 8.0 | 8.3 to 8.7 |
| The class report query before #33, without the term | 26.3 + 1.7 | 42.9 + 29.8 |

Whole operations, wall clock from Django, two runs each:

| | Plain | Partitioned |
|---|---:|---:|
| PO scores of the 1,551 students in one class | 149 to 151 ms | 137 to 141 ms |
| Saving all 1,551 grades of one assessment | 2.47 to 2.48 s | 2.81 s |
| Grade table with its indexes | 73 MB | 81 MB |

Under load the times roughly doubled on both sides; the ratios held.

The class report plain, with the term index:

```
Hash Join
  ->  Hash Join
        ->  Seq Scan on grading_enrollment
        ->  Hash
              ->  Index Scan using grading_grade_term_id_idx on grading_grade
                    Index Cond: (term_id = 20)
                    Filter: (enrollment_id = ANY ('{...}'::bigint[]))
  ->  Hash
        ->  Seq Scan on grading_assessment
```

Partitioned, only `grading_grade_part_20` is planned and read:

```
Hash Join
  ->  Nested Loop
        ->  Index Scan using grading_grade_part_20_enrollment_id_idx on grading_grade_part_20 grading_grade
              Index Cond: (enrollment_id = ANY ('{...}'::bigint[]))
              Filter: (term_id = 20)
        ->  Memoize
              ->  Index Scan using grading_enrollment_pkey on grading_enrollment
  ->  Hash
        ->  Seq Scan on grading_assessment
```

It touches more buffers than the plain plan (8,200 against 1,300). The gain is the plan: the plain table has to
filter the class's students out of 50,000 rows of the term and hash them against every enrollment, while the
partition's own enrollment index finds the class's rows directly.

A query that cannot name the term reads every partition, for example a grade by id:

```
Append
  ->  Index Scan using grading_grade_part_1_pkey on grading_grade_part_1 grading_grade_1
        Index Cond: (id = 38)
  ->  Index Scan using grading_grade_part_2_pkey on grading_grade_part_2 grading_grade_2
  ...  (one per partition)
```

## What it means

- The class report's grade query is three times faster, and a class's PO scores about 7% faster overall.
- Every query that cannot name the term pays planning time that grows with the number of partitions: half a
  millisecond at 20 terms. The query from before #33 became much slower (43 + 30 ms), which is why the app names the
  term everywhere it can.
- Saving a class's grades is about 13% slower (2.8 s against 2.5 s for 1,551 grades).
- A term's statistics are not faster: an index on `term_id` already finds a term's rows in the plain table.
- At this size the main gain is still to come: an old term can be detached and archived
  (`ALTER TABLE grading_grade DETACH PARTITION grading_grade_part_<id>`) without deleting rows one by one.

## Reproducing

Set `DATABASE_URL` to an empty database, here `aculator`, then:

```
python manage.py migrate
python manage.py fake_data --years 10 --students 20000      # about 3 minutes
python manage.py benchmark_partition > partitioned.md

createdb -T aculator aculator_plain
psql aculator_plain <<'SQL'
BEGIN;
CREATE TABLE grading_grade_plain (LIKE grading_grade INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING IDENTITY);
INSERT INTO grading_grade_plain SELECT * FROM grading_grade;
DROP TABLE grading_grade CASCADE;   -- also drops the score views, which the benchmark does not read
ALTER TABLE grading_grade_plain RENAME TO grading_grade;
SELECT setval(pg_get_serial_sequence('grading_grade', 'id'), (SELECT max(id) FROM grading_grade));
ALTER TABLE grading_grade ADD PRIMARY KEY (id), ADD CONSTRAINT uniq_grade UNIQUE (enrollment_id, assessment_id),
    ADD FOREIGN KEY (enrollment_id) REFERENCES grading_enrollment (id) DEFERRABLE INITIALLY DEFERRED,
    ADD FOREIGN KEY (assessment_id) REFERENCES grading_assessment (id) DEFERRABLE INITIALLY DEFERRED,
    ADD FOREIGN KEY (term_id) REFERENCES grading_term (id) DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX ON grading_grade (enrollment_id);
CREATE INDEX ON grading_grade (assessment_id);
CREATE INDEX ON grading_grade (term_id);
CREATE TRIGGER grading_grade_change_history AFTER INSERT OR UPDATE OR DELETE ON grading_grade
    FOR EACH ROW EXECUTE FUNCTION grading_record_grade_change();
COMMIT;
VACUUM ANALYZE grading_grade;
SQL
DATABASE_URL=postgres://localhost/aculator_plain python manage.py benchmark_partition > plain.md
```
