# Course report: service vs materialized views (#79)

The course report now reads LO and PO scores from `student_lo_scores` and
`course_po_scores` instead of computing them with the service on every request.
The service stays as the reference the views are tested against.

## Correctness

- `CourseReportFromViewsTests` loads the fake data (plus one absent grade and
  one zero weight, which the fake data lacks) and checks that every offering's
  report scores and evidence counts equal the service's.
- Run by hand on the full fake data (400 students, 64 offerings, 2400
  enrollments): no difference.
- End to end on a real database: a CSV import through the import page commits,
  the views refresh after the commit (`signals.py`), and the report shows the
  new score.

## Queries

| | Queries on the report page |
|---|---:|
| Service | 11 |
| Views | 13 |

The count does not grow with the class size.

## Time

Median of 9 runs of the scoring call, `fake_data --students 4000`
(24,000 enrollments, 96,000 grades), PostgreSQL 15 on a laptop.

| Students in the offering | Service | Views |
|---:|---:|---:|
| 72 | 12 ms | 10 ms |
| 849 | 79 ms | 42 ms |

The views' unique indexes start with `student_id`, so reading one offering
scans the whole view; an index on `offering_id` brings the 849 student case to
33 ms. The score tables in #79's follow-up have their primary key start with
`offering_id`, which covers this.

## Open

Every score change refreshes all three views over the whole database after the
commit, inside the request: 0.27 s with 400 students, about 4 s with 4000. The
follow-up branch `fix/79-score-tables` recomputes only the changed offering.
