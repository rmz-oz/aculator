"""Table sizes and query times with and without indexes (#15).

    python manage.py fake_data
    python manage.py measure_db --output docs/measurements.md

Every table and materialized view in the public schema gets its exact row
count, column count and sizes. Then a few queries the app really runs are
timed with EXPLAIN ANALYZE, once with the planner free to use indexes and
once with index, index-only and bitmap scans switched off for that
transaction only (SET LOCAL, rolled back). Each query runs a few times to
warm the cache, then --runs times; the median is reported because single
runs on a laptop jump around.
"""

import statistics
import time
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from grading.materialized_views import refresh_materialized_views

WARMUP = 3

TABLES_SQL = """
SELECT c.relname,
       CASE c.relkind WHEN 'm' THEN 'materialized view' ELSE 'table' END,
       (SELECT count(*) FROM pg_attribute a
         WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped),
       pg_table_size(c.oid), pg_indexes_size(c.oid), pg_total_relation_size(c.oid)
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'm')
ORDER BY pg_total_relation_size(c.oid) DESC, c.relname
"""

INDEXES_SQL = """
SELECT t.relname, i.relname, pg_relation_size(i.oid), pg_get_indexdef(i.oid)
FROM pg_index x
JOIN pg_class i ON i.oid = x.indexrelid
JOIN pg_class t ON t.oid = x.indrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname = 'public' AND t.relname IN ('grading_grade', 'grading_enrollment', 'cross_course_po_scores')
ORDER BY t.relname, i.relname
"""

# (name, where in the app, SQL, query that picks its one %s parameter or None)
QUERIES = (
    (
        "Grades of one enrollment",
        "scoring service, one student in one course",
        "SELECT * FROM grading_grade WHERE enrollment_id = %s",
        "SELECT id FROM grading_enrollment ORDER BY id OFFSET (SELECT count(*) / 2 FROM grading_enrollment) LIMIT 1",
    ),
    (
        "Grades of one class",
        "class report, every grade in one offering",
        ("SELECT g.* FROM grading_grade g JOIN grading_enrollment e ON e.id = g.enrollment_id"
        " WHERE e.offering_id = %s"),
        ("SELECT id FROM grading_courseoffering ORDER BY id OFFSET (SELECT count(*) / 2 FROM grading_courseoffering)"
        " LIMIT 1"),
    ),
    (
        "PO scores of one student",
        "student profile, from cross_course_po_scores",
        "SELECT * FROM cross_course_po_scores WHERE student_id = %s",
        ("SELECT student_id FROM cross_course_po_scores GROUP BY student_id ORDER BY student_id"
        " OFFSET (SELECT count(DISTINCT student_id) / 2 FROM cross_course_po_scores) LIMIT 1"),
    ),
    (
        "Department mean per PO",
        "student profile, reads every row of the view",
        "SELECT program_outcome_id, avg(score) FROM cross_course_po_scores GROUP BY program_outcome_id",
        None,
    ),
)


def size(n):
    for unit in ("bytes", "kB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,.0f} {unit}" if unit == "bytes" else f"{n:,.1f} {unit}"
        n /= 1024
    return str(n)


def ms(values):
    return f"{statistics.median(values):.3f}"


class Command(BaseCommand):
    help = "Measure table sizes and query times with and without indexes, as Markdown."

    def add_arguments(self, parser):
        parser.add_argument("--runs", type=int, default=30, help="Timed runs per query and setting.")
        parser.add_argument("--output", help="Write the Markdown here instead of stdout.")

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError("measure_db needs PostgreSQL.")
        runs = options["runs"]
        if runs < 1:
            raise CommandError("--runs must be at least 1.")

        with connection.cursor() as cursor:
            # Fresh planner statistics first: right after fake_data autovacuum
            # may not have run, and stale row estimates pick the wrong plans.
            cursor.execute("ANALYZE")
            cursor.execute("SHOW server_version")
            version = cursor.fetchone()[0].split()[0]
            cursor.execute(TABLES_SQL)
            tables = cursor.fetchall()
            counts = {}
            for name, *_ in tables:
                cursor.execute(f'SELECT count(*) FROM "{name}"')
                counts[name] = cursor.fetchone()[0]
            cursor.execute(INDEXES_SQL)
            indexes = cursor.fetchall()

        timings = []
        for name, used_by, sql, pick in QUERIES:
            params = []
            if pick:
                with connection.cursor() as cursor:
                    cursor.execute(pick)
                    row = cursor.fetchone()
                if row is None:
                    raise CommandError("No data to measure. Run `python manage.py fake_data` first.")
                params = [row[0]]
            with_index, with_plan = self.time_query(sql, params, runs, indexes_on=True)
            without_index, without_plan = self.time_query(sql, params, runs, indexes_on=False)
            shown = sql % tuple(params) if params else sql
            timings.append((name, used_by, shown, with_index, with_plan, without_index, without_plan))

        refresh = []
        for _ in range(max(3, min(runs, 10))):
            start = time.perf_counter()
            refresh_materialized_views()
            refresh.append((time.perf_counter() - start) * 1000)

        text = self.render(version, runs, tables, counts, indexes, timings, refresh)
        if options["output"]:
            with open(options["output"], "w", encoding="utf-8") as f:
                f.write(text)
            self.stdout.write(f"Wrote {options['output']}.")
        else:
            self.stdout.write(text)

    def time_query(self, sql, params, runs, indexes_on):
        """Median execution time in ms and the top plan node, from EXPLAIN ANALYZE."""
        times = []
        plan = None
        with transaction.atomic():
            with connection.cursor() as cursor:
                if not indexes_on:
                    for setting in ("enable_indexscan", "enable_indexonlyscan", "enable_bitmapscan"):
                        cursor.execute(f"SET LOCAL {setting} = off")
                for i in range(WARMUP + runs):
                    cursor.execute(f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}", params or None)
                    result = cursor.fetchone()[0]
                    result = result[0] if isinstance(result, list) else result
                    if i >= WARMUP:
                        times.append(result["Execution Time"])
                        plan = scan_nodes(result["Plan"])
            transaction.set_rollback(True)
        return times, plan

    def render(self, version, runs, tables, counts, indexes, timings, refresh):
        out = [
            "# Table sizes and index measurements",
            "",
            (f"Measured {date.today().isoformat()} on PostgreSQL {version}, local machine, data from"
            " `python manage.py fake_data`. Rerun with `python manage.py measure_db --output docs/measurements.md`;"
            " absolute times depend on the machine, the ratios are what to compare."),
            "",
            "## Tables and materialized views",
            "",
            ("Exact row counts (`count(*)`). Sizes from `pg_table_size`, `pg_indexes_size` and"
            " `pg_total_relation_size`; table size includes TOAST and the free space map."),
            "",
            "| Name | Kind | Rows | Columns | Table | Indexes | Total |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        for name, kind, columns, table, index, total in tables:
            out.append(
                f"| `{name}` | {kind} | {counts[name]:,} | {columns} | {size(table)} | {size(index)} | {size(total)} |"
            )
        out += [
            "",
            "## Indexes on the tables the queries read",
            "",
            "| Table | Index | Size | Definition |",
            "|---|---|---:|---|",
        ]
        for table, name, nbytes, definition in indexes:
            columns = definition[definition.index("USING"):]
            out.append(f"| `{table}` | `{name}` | {size(nbytes)} | `{columns}` |")
        out += [
            "",
            "## Query times",
            "",
            (f"Each query ran {WARMUP} times to warm the cache, then {runs} times with indexes allowed and {runs} times"
            " with `enable_indexscan`, `enable_indexonlyscan` and `enable_bitmapscan` off for that transaction only."
            " Times are the median of `Execution Time` from `EXPLAIN (ANALYZE, FORMAT JSON)`, planning not included."),
            "",
            "| Query | Used by | With indexes (ms) | Plan | Without (ms) | Plan | Ratio |",
            "|---|---|---:|---|---:|---|---:|",
        ]
        for name, used_by, _, with_index, with_plan, without_index, without_plan in timings:
            ratio = statistics.median(without_index) / statistics.median(with_index)
            out.append(
                f"| {name} | {used_by} | {ms(with_index)} | {with_plan} | {ms(without_index)} | {without_plan}"
                f" | {ratio:.1f}x |"
            )
        out += ["", "The SQL, with the parameter the run used:", ""]
        for name, _, sql, *_ in timings:
            out += [f"- {name}: `{sql}`"]
        out += [
            "",
            "## Refreshing the materialized views",
            "",
            (f"`refresh_materialized_views()` refreshes all three views concurrently after every committed change to a"
            f" score input. Median of {len(refresh)} runs: **{statistics.median(refresh):.0f} ms**"
            f" (min {min(refresh):.0f}, max {max(refresh):.0f})."),
            "",
            "## Reading the numbers",
            "",
            ("- A selective lookup (one enrollment, one class, one student) is where the B-tree indexes pay off: without"
            " them PostgreSQL reads the whole table and filters."),
            ("- The department mean reads every row of the view either way, so the index cannot help and the two times"
            " match. It is the control row."),
            ("- Indexes cost space: on `grading_grade` they are about as large as the table itself, and every grade"
            " insert updates them too."),
            ("- Planner statistics matter as much as the index. Measured right after `fake_data`, before `ANALYZE`, the"
            " class query read all of `grading_grade` with a sequential scan and the index gave 1.1x; with fresh"
            " statistics it uses the `enrollment_id` index and gives the ratio above. The command runs `ANALYZE` first."),
            ("- Every committed change to a score input pays for the refresh above, inside the request. A CSV import"
            " pays it once for the whole file, saving grades one by one in the admin pays it per grade."),
            "- Times are medians on one machine with warm cache. They are not a benchmark of the server.",
            "",
        ]
        return "\n".join(out)


def scan_nodes(plan):
    """The scan types in a plan tree, e.g. 'Index Scan' or 'Hash Join, Seq Scan, Seq Scan'."""
    found = []

    def walk(node):
        kind = node["Node Type"]
        if "Scan" in kind:
            found.append(kind)
        for child in node.get("Plans", []):
            walk(child)

    walk(plan)
    return ", ".join(dict.fromkeys(found)) or plan["Node Type"]
