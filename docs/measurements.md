# Database Index and Table Size Measurements

## 1. Objective

The objective of this task is to measure database table sizes, row counts, column counts, index storage usage, and query execution performance in the Aculator project.

The measurements were performed using PostgreSQL 16 and a local database populated with synthetic test data.

## 2. Table Size Measurements

The following measurements were collected on November 19, 2026.

| Table | Rows | Columns | Table Size | Index Size | Total Size |
|---|---:|---:|---:|---:|---:|
| grading_grade | 12800 | 5 | 824 kB | 1080 kB | 1904 kB |
| grading_enrollment | 3200 | 3 | 200 kB | 376 kB | 576 kB |
| grading_lopoweight | 942 | 4 | 152 kB | 208 kB | 360 kB |
| grading_assessmentloweight | 768 | 4 | 72 kB | 136 kB | 208 kB |
| grading_learningoutcome | 192 | 4 | 48 kB | 48 kB | 96 kB |
| grading_assessment | 256 | 4 | 40 kB | 48 kB | 88 kB |
| grading_courseoffering | 64 | 3 | 8192 bytes | 64 kB | 72 kB |
| grading_pocomponent | 5 | 4 | 16 kB | 48 kB | 64 kB |
| grading_programoutcome | 5 | 3 | 16 kB | 48 kB | 64 kB |
| grading_course | 8 | 4 | 8192 bytes | 48 kB | 56 kB |
| grading_term | 8 | 3 | 8192 bytes | 32 kB | 40 kB |
| grading_courseoffering_instructors | 0 | 3 | 0 bytes | 32 kB | 32 kB |

Row counts were obtained using `COUNT(*)`. Column counts were obtained from `information_schema.columns`. Storage sizes were obtained using PostgreSQL's `pg_table_size`, `pg_indexes_size`, and `pg_total_relation_size` functions.

## 3. Index Performance Measurements

### Test Query

```sql
SELECT *
FROM grading_grade
WHERE enrollment_id = 161;
```

The `grading_grade` table contained 12,800 rows. The query returned four matching rows.

### Methodology

Query execution plans and execution times were collected using `EXPLAIN (ANALYZE, BUFFERS)`.

The default PostgreSQL query plan used the B-tree index `grading_grade_enrollment_id_8fc240c9`.

For the sequential scan comparison, index scan, index-only scan, and bitmap scan methods were disabled temporarily using transaction-local PostgreSQL settings. The settings were reverted using `ROLLBACK`.

Three additional execution measurements were collected for each scan method.

### Results

| Run | Index Scan (ms) | Sequential Scan (ms) |
|---|---:|---:|
| 1 | 0.126 | 1.539 |
| 2 | 0.049 | 1.120 |
| 3 | 0.026 | 1.061 |
| Average | 0.067 | 1.240 |

The indexed query was approximately **18.5 times faster** based on the arithmetic mean of these three execution measurements.

### Buffer Usage

The repeated indexed queries reported three shared buffer hits per execution.

The sequential scan queries reported 99 shared buffer hits per execution and filtered out 12,796 nonmatching rows.

## 4. Observations

- `grading_grade` was the largest grading table, containing 12,800 records.
- The indexes on `grading_grade` occupied more disk space than the table data itself.
- The indexed lookup was faster than the sequential scan in the measured runs.
- Indexes introduce additional storage overhead but can improve selective lookup performance.
- The `grading_courseoffering_instructors` table contained no records at measurement time.

## 5. Limitations

These measurements were performed on a local PostgreSQL instance using synthetic data.

The performance comparison covered one equality-filter query on `grading_grade.enrollment_id`.

The three measurements per scan method were performed sequentially rather than in randomized order. Caching, background system activity, and execution-plan differences may affect timings.

The reported speedup is specific to this dataset, query, and measurement environment. It should not be generalized to all database operations.

## 6. Conclusion

The measurements demonstrate the storage overhead associated with database indexes and their potential performance benefits for selective queries.

For the tested `enrollment_id` lookup, PostgreSQL's index scan performed substantially faster than the sequential scan.

Further benchmarks involving joins, larger datasets, and different query selectivities would provide a more comprehensive evaluation of database performance.