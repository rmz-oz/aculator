"""Reading grade CSV files for one assessment (#13).

A file has a header row with the columns student_number and score, in any
order and case. Comma separated files use a dot for decimals. Files saved by
Excel with a Turkish locale use semicolons and a decimal comma; both work.
Nothing here writes to the database, the view does that in one transaction.
"""

import csv
import hashlib
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from io import StringIO

from django.db import OperationalError, connection, transaction

COLUMNS = {"student_number", "score"}
MAX_FILE_SIZE = 1024 * 1024
CENT = Decimal("0.01")


@dataclass
class ParsedFiles:
    rows: list = field(default_factory=list)  # (enrollment, score)
    errors: list = field(default_factory=list)
    locations: dict = field(default_factory=dict)  # student number -> first "file, line N"


def parse_grade_files(files, assessment, enrollments):
    """Check every row of every file. `enrollments` maps student number to Enrollment.

    A student may appear only once across all files, so two lists that both
    grade the same student are an error instead of a silent overwrite.
    """
    parsed = ParsedFiles()
    for uploaded in files:
        if uploaded.size > MAX_FILE_SIZE:
            parsed.errors.append(f"{uploaded.name}: File is larger than 1 MB.")
            continue
        try:
            text = uploaded.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            parsed.errors.append(f'{uploaded.name}: File is not UTF-8. Save it as "CSV UTF-8" and try again.')
            continue
        try:
            _parse_file(uploaded.name, text, assessment, enrollments, parsed)
        except csv.Error as error:
            parsed.errors.append(f"{uploaded.name}: File could not be read ({error}).")
    return parsed


def _parse_file(name, text, assessment, enrollments, parsed):
    if not text.strip():
        parsed.errors.append(f"{name}: File is empty.")
        return

    first_line = text.splitlines()[0]
    delimiter = ";" if ";" in first_line and "," not in first_line else ","
    reader = csv.reader(StringIO(text), delimiter=delimiter, strict=True)
    header = [column.strip().lower() for column in next(reader)]
    if len(header) != len(COLUMNS) or set(header) != COLUMNS:
        parsed.errors.append(f"{name}: The first row must be student_number,score.")
        return
    number_at = header.index("student_number")
    score_at = header.index("score")

    has_rows = False
    for values in reader:
        if not any(value.strip() for value in values):
            continue
        has_rows = True
        location = f"{name}, line {reader.line_num}"
        if len(values) != len(header):
            parsed.errors.append(f"{location}: Expected 2 columns, found {len(values)}.")
            continue

        number = values[number_at].strip()
        enrollment = enrollments.get(number)
        if not number:
            parsed.errors.append(f"{location}: Student number is empty.")
        elif enrollment is None:
            parsed.errors.append(f"{location}: {number} is not enrolled in this course.")
        if number in parsed.locations:
            parsed.errors.append(f"{location}: {number} appears again, first at {parsed.locations[number]}.")
            enrollment = None
        elif number:
            parsed.locations[number] = location

        raw_score = values[score_at].strip()
        if delimiter == ";":
            raw_score = raw_score.replace(",", ".")
        score, error = validate_score(raw_score, assessment.max_score)
        if error:
            parsed.errors.append(f"{location}: {error}")
        elif enrollment is not None:
            parsed.rows.append((enrollment, score))

    if not has_rows:
        parsed.errors.append(f"{name}: File has no grade rows.")


def validate_score(raw, max_score):
    try:
        score = Decimal(raw)
    except InvalidOperation:
        return None, "Score must be a number."
    if not score.is_finite() or not 0 <= score <= max_score:
        return None, f"Score must be between 0 and {max_score}."
    if score != score.quantize(CENT):
        return None, "Score can have at most two decimal places."
    return score.quantize(CENT), None

def validate_pasted_grades(rows, assessment, enrollments):
    """Return validated scores and errors addressed by grid row and field."""
    scores = []
    errors = []
    seen = set()

    for index, row in enumerate(rows):
        number = row["student_number"].strip()
        raw_score = row["score"].strip()

        if not raw_score:
            continue

        enrollment = enrollments.get(number)
        number_error = None

        if not number:
            number_error = "Student number is empty."
        elif enrollment is None:
            number_error = "Student is not enrolled in this course."
        elif number in seen:
            number_error = "Student appears more than once."

        if number:
            seen.add(number)

        if number_error:
            errors.append({
                "row": index,
                "field": "student_number",
                "message": number_error,
            })

        score, score_error = validate_score(
            raw_score.replace(",", "."),
            assessment.max_score,
        )
        if score_error:
            errors.append({
                "row": index,
                "field": "score",
                "message": score_error,
            })

        if not number_error and not score_error:
            scores.append((enrollment.pk, score))

    return scores, errors


def grades_fingerprint(assessment):
    """A hash of the assessment's current grades.

    A preview stores it; the confirm step compares it, so a preview cannot be
    confirmed after someone else changed the grades or after it was already
    confirmed once.
    """
    rows = assessment.grades.order_by("enrollment_id").values_list("enrollment_id", "status", "score")
    text = ";".join(f"{enrollment_id},{status},{score}" for enrollment_id, status, score in rows)
    return hashlib.sha256(text.encode()).hexdigest()


@contextmanager
def serializable_transaction():
    """transaction.atomic() at SERIALIZABLE (docs/decisions/0008).

    SET TRANSACTION has to be the first statement of the transaction, so this
    cannot run inside another atomic block.
    """
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        yield


def is_serialization_failure(error):
    return isinstance(error, OperationalError) and getattr(error.__cause__, "sqlstate", None) == "40001"
