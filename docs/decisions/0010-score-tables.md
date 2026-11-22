# 10. Score tables recomputed per offering

The three score views of #9 were refreshed in full after every committed change to a score input, inside the
request. That recomputed every grade in the database: an import waited 0.3 s with 400 students and about 4 s with
4000, and the cost grew with the database, not with the change.

Migration 0013 turns `student_lo_scores` and `cross_course_po_scores` into tables with the same columns, adds
`student_component_scores`, and makes `course_po_scores` a plain view over it, so readers do not change. The SQL
function `refresh_scores(offerings, students)` deletes and recomputes the rows of the changed offerings, then the
cross-course rows of their students. The SQL is the views' SQL, so the numbers are the same to the last digit
(checked on the 4000 student fake data before and after the migration).

The department mean per PO stays a materialized view, `department_po_means`, one row per PO. It is refreshed
concurrently at the end of every `refresh_scores` call, in a few milliseconds.

`grading/signals.py` collects which offerings, assessments, LOs and students a transaction changed, old and new
foreign keys both, and calls `refresh_scores` once after the commit. A PO component change recomputes everything.

Why after the commit, in its own transaction: inside the SERIALIZABLE import (decision 0008) two imports of different
courses that share students would rewrite the same cross-course rows and one would fail with 409. An advisory lock in
`refresh_scores` makes refreshes wait for each other, so two of them never delete and insert the same student at once.

Measured on a laptop, one import through the import page:

| Fake data | Students in the course | Before | After |
|---|---:|---:|---:|
| 400 students | 31 | 333 ms | 64 ms |
| 400 students | 92 | 396 ms | 160 ms |
| 4000 students | 72 | 4.3 s | 0.24 s |
| 4000 students | 849 | 6.4 s | 1.9 s |

Of the 1.9 s, `refresh_scores` is 0.24 s; the rest is the import saving each grade.

Limits: `bulk_create`, `QuerySet.update` and raw SQL send no signal. Code that writes that way calls
`refresh_materialized_views()`, which recomputes everything (`fake_data`, the demo data, `manage.py
refresh_materialized_views` after restoring a backup). Rejected: plain views (the department mean took 2 to 3 s on
every profile), pg_ivm (an extension, not in the stock `postgres:16` image that CI and docker compose use), and a
background refresh (no worker on the free Render plan, and reports would lag behind the import).

Tests in `grading/test_score_tables.py` change one thing at a time with no full refresh and compare the tables with the
calculation service and with a full rebuild; they also run imports and refreshes from two threads at once.
