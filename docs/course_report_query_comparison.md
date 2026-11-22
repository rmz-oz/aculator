# Course Report Query Comparison

## Objective
Replace the Course Report calculation service with materialized view reads while preserving report correctness.

## SQL Query Counts

| Implementation | SQL Queries |
|---|---:|
| Previous calculation service | 11 |
| Materialized view implementation | 13 |

## Query Scaling

The materialized view implementation executed 13 SQL queries
with both 2 and 12 enrolled students.

No per-student query growth was observed in this test.

## Correctness

- LO and PO scores were compared against the previous service.
- Class averages were verified.
- Low-evidence and no-evidence cases were tested.
- All 12 CourseReportViewTests passed.

## Conclusion

The materialized view implementation preserves the tested report
behavior and avoids N+1 query growth.

However, the SQL query count increased from 11 to 13.
Further optimization may reduce the additional queries.

Materialized views must be refreshed after relevant data changes
before reports can reflect updated scores.