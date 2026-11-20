
# Sprint 4 — Grade Partitioning Benchmark

## Objective

Compare query performance between an indexed, unpartitioned Grade table and a Grade table partitioned by academic term.

## Dataset

- Total Grade records: 9,600
- Academic terms: 20
- Academic years: 2023–2032
- Database: PostgreSQL 16
- Test database: aculator_sprint4_test

## Benchmark Query

```sql
SELECT *
FROM grading_grade_unpartitioned_test
WHERE term_id = 21;
```

```sql
SELECT *
FROM grading_grade_partition_test
WHERE term_id = 21;
```

## Methodology

- 3 warm-up executions per query
- 10 measured executions per query
- EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
- Median execution and planning times reported
- The unpartitioned table has an index on term_id

## Results

| Metric | Unpartitioned (Indexed) | Partitioned |
|---|---:|---:|
| Median Execution Time | 0.0445 ms | 0.0250 ms |
| Median Planning Time | 0.0315 ms | 0.0255 ms |
| Sum of Medians | 0.0760 ms | 0.0505 ms |

## Analysis

The partitioned table achieved approximately 43.8% lower median execution time for the tested term-specific query.

PostgreSQL successfully performed partition pruning, scanning only the relevant partition instead of the entire partitioned table.

However, the dataset is relatively small and execution times are measured in microseconds. These results are preliminary and do not establish a general performance improvement across different workloads or dataset sizes.

## Limitations

- Only one academic term was tested.
- The dataset contains 9,600 Grade records.
- Measurements were performed in a local test environment.
- The benchmark uses experimental tables rather than the production Django Grade table.
- The reported sum of medians is not a directly measured end-to-end query latency.

## Conclusion

Term-based partitioning was successfully demonstrated in an isolated PostgreSQL test environment. Additional testing and a safe Django migration are required before applying partitioning to the actual Grade table.
