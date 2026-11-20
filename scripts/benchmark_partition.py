import json
import statistics

import psycopg

DATABASE_URL = (
    "postgres://postgres:postgres@localhost:5432/"
    "aculator_sprint4_test"
)

QUERIES = {
    "Unpartitioned (indexed)": """
        SELECT *
        FROM grading_grade_unpartitioned_test
        WHERE term_id = 21
    """,
    "Partitioned": """
        SELECT *
        FROM grading_grade_partition_test
        WHERE term_id = 21
    """,
}

with psycopg.connect(DATABASE_URL) as conn:
    for name, query in QUERIES.items():
        execution_times = []
        planning_times = []

        with conn.cursor() as cursor:
            for i in range(13):
                cursor.execute(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
                    + query
                )

                result = cursor.fetchone()[0]
                plan = (
                    json.loads(result)[0]
                    if isinstance(result, str)
                    else result[0]
                )

                if i >= 3:
                    execution_times.append(plan["Execution Time"])
                    planning_times.append(plan["Planning Time"])

        print(f"\n{name}")
        print(
            "Median execution:",
            round(statistics.median(execution_times), 4),
            "ms",
        )
        print(
            "Median planning:",
            round(statistics.median(planning_times), 4),
            "ms",
        )