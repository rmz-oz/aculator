# Table sizes and index measurements

Measured 2026-11-19 on PostgreSQL 16.15, local machine, data from `python manage.py fake_data`. Rerun with `python manage.py measure_db --output docs/measurements.md`; absolute times depend on the machine, the ratios are what to compare.

## Tables and materialized views

Exact row counts (`count(*)`). Sizes from `pg_table_size`, `pg_indexes_size` and `pg_total_relation_size`; table size includes TOAST and the free space map.

| Name | Kind | Rows | Columns | Table | Indexes | Total |
|---|---|---:|---:|---:|---:|---:|
| `course_po_scores` | materialized view | 12,177 | 4 | 864.0 kB | 608.0 kB | 1.4 MB |
| `grading_grade` | table | 9,600 | 5 | 672.0 kB | 800.0 kB | 1.4 MB |
| `student_lo_scores` | materialized view | 7,200 | 4 | 520.0 kB | 312.0 kB | 832.0 kB |
| `cross_course_po_scores` | materialized view | 4,291 | 3 | 328.0 kB | 152.0 kB | 480.0 kB |
| `grading_enrollment` | table | 2,400 | 3 | 160.0 kB | 272.0 kB | 432.0 kB |
| `auth_user` | table | 400 | 11 | 152.0 kB | 192.0 kB | 344.0 kB |
| `grading_assessmentloweight` | table | 960 | 4 | 88.0 kB | 240.0 kB | 328.0 kB |
| `grading_lopoweight` | table | 973 | 4 | 88.0 kB | 200.0 kB | 288.0 kB |
| `grading_assessment` | table | 640 | 4 | 64.0 kB | 112.0 kB | 176.0 kB |
| `grading_learningoutcome` | table | 480 | 4 | 64.0 kB | 96.0 kB | 160.0 kB |
| `grading_courseoffering` | table | 160 | 3 | 40.0 kB | 64.0 kB | 104.0 kB |
| `grading_pocomponent` | table | 11 | 4 | 16.0 kB | 48.0 kB | 64.0 kB |
| `grading_programoutcome` | table | 11 | 3 | 16.0 kB | 48.0 kB | 64.0 kB |
| `auth_group` | table | 3 | 2 | 8.0 kB | 48.0 kB | 56.0 kB |
| `auth_permission` | table | 68 | 4 | 8.0 kB | 48.0 kB | 56.0 kB |
| `grading_course` | table | 8 | 4 | 8.0 kB | 48.0 kB | 56.0 kB |
| `django_content_type` | table | 17 | 3 | 8.0 kB | 32.0 kB | 40.0 kB |
| `grading_term` | table | 20 | 3 | 8.0 kB | 32.0 kB | 40.0 kB |
| `auth_group_permissions` | table | 0 | 3 | 0 bytes | 32.0 kB | 32.0 kB |
| `auth_user_groups` | table | 0 | 3 | 0 bytes | 32.0 kB | 32.0 kB |
| `auth_user_user_permissions` | table | 0 | 3 | 0 bytes | 32.0 kB | 32.0 kB |
| `django_admin_log` | table | 0 | 8 | 8.0 kB | 24.0 kB | 32.0 kB |
| `django_migrations` | table | 23 | 4 | 16.0 kB | 16.0 kB | 32.0 kB |
| `django_session` | table | 0 | 3 | 8.0 kB | 24.0 kB | 32.0 kB |
| `grading_courseoffering_instructors` | table | 0 | 3 | 0 bytes | 32.0 kB | 32.0 kB |

## Indexes on the tables the queries read

| Table | Index | Size | Definition |
|---|---|---:|---|
| `cross_course_po_scores` | `cross_course_po_scores_unique` | 152.0 kB | `USING btree (student_id, program_outcome_id)` |
| `grading_enrollment` | `grading_enrollment_offering_id_18fd2ea9` | 40.0 kB | `USING btree (offering_id)` |
| `grading_enrollment` | `grading_enrollment_pkey` | 72.0 kB | `USING btree (id)` |
| `grading_enrollment` | `grading_enrollment_student_id_8213fb46` | 48.0 kB | `USING btree (student_id)` |
| `grading_enrollment` | `uniq_enrollment` | 112.0 kB | `USING btree (offering_id, student_id)` |
| `grading_grade` | `grading_grade_assessment_id_dbc8c459` | 120.0 kB | `USING btree (assessment_id)` |
| `grading_grade` | `grading_grade_enrollment_id_8fc240c9` | 136.0 kB | `USING btree (enrollment_id)` |
| `grading_grade` | `grading_grade_pkey` | 232.0 kB | `USING btree (id)` |
| `grading_grade` | `uniq_grade` | 312.0 kB | `USING btree (enrollment_id, assessment_id)` |

## Query times

Each query ran 3 times to warm the cache, then 5 times with indexes allowed and 5 times with `enable_indexscan`, `enable_indexonlyscan` and `enable_bitmapscan` off for that transaction only. Times are the median of `Execution Time` from `EXPLAIN (ANALYZE, FORMAT JSON)`, planning not included.

| Query | Used by | With indexes (ms) | Plan | Without (ms) | Plan | Ratio |
|---|---|---:|---|---:|---|---:|
| Grades of one enrollment | scoring service, one student in one course | 0.003 | Index Scan | 0.224 | Seq Scan | 74.7x |
| Grades of one class | class report, every grade in one offering | 0.025 | Bitmap Heap Scan, Bitmap Index Scan, Index Scan | 0.716 | Seq Scan | 28.6x |
| PO scores of one student | student profile, from cross_course_po_scores | 0.004 | Index Scan | 0.077 | Seq Scan | 19.2x |
| Department mean per PO | student profile, reads every row of the view | 0.442 | Seq Scan | 0.442 | Seq Scan | 1.0x |

The SQL, with the parameter the run used:

- Grades of one enrollment: `SELECT * FROM grading_grade WHERE enrollment_id = 1201`
- Grades of one class: `SELECT g.* FROM grading_grade g JOIN grading_enrollment e ON e.id = g.enrollment_id WHERE e.offering_id = 241`
- PO scores of one student: `SELECT * FROM cross_course_po_scores WHERE student_id = 601`
- Department mean per PO: `SELECT program_outcome_id, avg(score) FROM cross_course_po_scores GROUP BY program_outcome_id`

## Refreshing the materialized views

`refresh_materialized_views()` refreshes all three views concurrently after every committed change to a score input. Median of 5 runs: **103 ms** (min 100, max 110).

## Reading the numbers

- A selective lookup (one enrollment, one class, one student) is where the B-tree indexes pay off: without them PostgreSQL reads the whole table and filters.
- The department mean reads every row of the view either way, so the index cannot help and the two times match. It is the control row.
- Indexes cost space: on `grading_grade` they are about as large as the table itself, and every grade insert updates them too.
- Planner statistics matter as much as the index. Measured right after `fake_data`, before `ANALYZE`, the class query read all of `grading_grade` with a sequential scan and the index gave 1.1x; with fresh statistics it uses the `enrollment_id` index and gives the ratio above. The command runs `ANALYZE` first.
- Every committed change to a score input pays for the refresh above, inside the request. A CSV import pays it once for the whole file, saving grades one by one in the admin pays it per grade.
- Times are medians on one machine with warm cache. They are not a benchmark of the server.
