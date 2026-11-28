"""Reading grade CSV files for one assessment (#13).

A file has a header row with the columns student_number and score, in any
order and case. Comma separated files use a dot for decimals. Files saved by
Excel with a Turkish locale use semicolons and a decimal comma; both work.
Nothing here writes to the database, the view does that in one transaction.
"""

import csv
import hashlib
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from io import BytesIO, StringIO
from zipfile import BadZipFile, ZipFile

from django.db import OperationalError, connection, transaction
from django.utils.formats import number_format
from django.utils.translation import gettext as _

COLUMNS = {"student_number", "score"}
MAX_FILE_SIZE = 1024 * 1024
CENT = Decimal("0.01")


@dataclass
class ParsedFiles:
    rows: list = field(default_factory=list)  # (enrollment, score)
    errors: list = field(default_factory=list)
    locations: dict = field(default_factory=dict)  # student number -> first "file, line N"

def _is_excel_workbook(content):
    if not content.startswith(b"PK\x03\x04"):
        return False

    try:
        with ZipFile(BytesIO(content)) as archive:
            return "xl/workbook.xml" in archive.namelist()
    except BadZipFile:
        return False

def parse_grade_files(files, assessment, enrollments):
    """Check every row of every file. `enrollments` maps student number to Enrollment.

    A student may appear only once across all files, so two lists that both
    grade the same student are an error instead of a silent overwrite.
    """
    parsed = ParsedFiles()
    for uploaded in files:
        if uploaded.size > MAX_FILE_SIZE:
            parsed.errors.append(_("%(name)s: File is larger than 1 MB.") % {"name": uploaded.name})
            continue

        content = uploaded.read()
        if _is_excel_workbook(content):
            parsed.errors.append(
                _('%(name)s: This file is an Excel workbook. '
                  'Open it in Excel and use Save As to export it as "CSV UTF-8".') % {"name": uploaded.name}
            )
            continue

        try:
            text = content.decode("utf-8-sig")

        except UnicodeDecodeError:
            parsed.errors.append(
                _('%(name)s: File is not UTF-8. Save it as "CSV UTF-8" and try again.') % {"name": uploaded.name}
            )
            continue
        try:
            _parse_file(uploaded.name, text, assessment, enrollments, parsed)
        except csv.Error as error:
            parsed.errors.append(_("%(name)s: File could not be read (%(error)s).") % {
                "name": uploaded.name, "error": error,
            })
    return parsed

def _has_trailing_empty_columns(columns):
    return len(columns) > len(COLUMNS) and all(
        not column.strip() for column in columns[len(COLUMNS):]
    )


def _header_error(first_line, header):
    if "\t" in first_line and ";" not in first_line and "," not in first_line:
        return _(
            "This file is tab-separated. Keep only the student number and score columns, "
            "name them student_number and score, and export as a comma- or "
            "semicolon-separated CSV UTF-8 file."
        )

    if {"öğrenci no", "not"}.issubset(header):
        return _(
            'The file uses Turkish column names. Rename "Öğrenci No" to student_number '
            'and "Not" to score, and keep only those two columns.'
        )

    if set(header[:len(COLUMNS)]) == COLUMNS and _has_trailing_empty_columns(header):
        return _(
            "The header has trailing empty columns. Delete the empty columns on the right "
            "and export the file again with only student_number and score."
        )

    return _("The first row must be student_number,score.")

def _unknown_student_error(number, enrollments):
    if re.fullmatch(r"[0-9]+(?:[.,][0-9]+)?[eE][+-]?[0-9]+", number):
        return _(
            "Student number %(number)s is in scientific notation. "
            "Set the student number column to Text in Excel, enter the original "
            "student number from the class list, and export the CSV again."
        ) % {"number": number}

    if re.fullmatch(r"[0-9]+", number) and any(
        enrolled_number.startswith("0")
        and len(enrolled_number) > len(number)
        and enrolled_number.lstrip("0") == number.lstrip("0")
        for enrolled_number in enrollments
    ):
        return _(
            "Student number %(number)s is missing one or more leading zeros. "
            "Restore them from the class list and keep the student number column "
            "formatted as Text when exporting the CSV."
        ) % {"number": number}

    return _("%(number)s is not enrolled in this course.") % {"number": number}

def _parse_file(name, text, assessment, enrollments, parsed):
    if not text.strip():
        parsed.errors.append(_("%(name)s: File is empty.") % {"name": name})
        return

    first_line = text.splitlines()[0]
    delimiter = ";" if ";" in first_line and "," not in first_line else ","
    reader = csv.reader(StringIO(text), delimiter=delimiter, strict=True)
    header = [column.strip().lower() for column in next(reader)]
    if len(header) != len(COLUMNS) or set(header) != COLUMNS:
        parsed.errors.append(_("%(name)s: %(error)s") % {"name": name, "error": _header_error(first_line, header)})
        return
    number_at = header.index("student_number")
    score_at = header.index("score")

    has_rows = False
    for values in reader:
        if not any(value.strip() for value in values):
            continue
        has_rows = True
        location = _("%(name)s, line %(line)s") % {"name": name, "line": reader.line_num}
        if len(values) != len(header):
            if _has_trailing_empty_columns(values):
                parsed.errors.append(
                    _("%(location)s: This row has trailing empty columns. "
                      "Remove the extra separators at the end of the row.") % {"location": location}
                )
            else:
                parsed.errors.append(_("%(location)s: Expected 2 columns, found %(n)s.") % {
                    "location": location, "n": len(values),
                })
            continue

        number = values[number_at].strip()
        enrollment = enrollments.get(number)
        if not number:
            parsed.errors.append(_("%(location)s: Student number is empty.") % {"location": location})
        elif enrollment is None:
            parsed.errors.append(_("%(location)s: %(error)s") % {
                "location": location, "error": _unknown_student_error(number, enrollments),
            })
        if number in parsed.locations:
            parsed.errors.append(_("%(location)s: %(number)s appears again, first at %(first)s.") % {
                "location": location, "number": number, "first": parsed.locations[number],
            })
            enrollment = None
        elif number:
            parsed.locations[number] = location

        raw_score = values[score_at].strip()
        if delimiter == "," and re.fullmatch(r"[+-]?[0-9]+,[0-9]+", raw_score):
            dot_score = raw_score.replace(",", ".")
            parsed.errors.append(
                _("%(location)s: Score %(score)s uses a decimal comma in a comma-separated CSV. "
                  "Use a decimal point (%(dot)s) or export the whole file with semicolon separators.") % {
                    "location": location, "score": raw_score, "dot": dot_score,
                }
            )
            continue
        if delimiter == ";":
            raw_score = raw_score.replace(",", ".")
        score, error = validate_score(raw_score, assessment.max_score)
        if error:
            parsed.errors.append(_("%(location)s: %(error)s") % {"location": location, "error": error})
        elif enrollment is not None:
            parsed.rows.append((enrollment, score))

    if not has_rows:
        parsed.errors.append(_("%(name)s: File has no grade rows.") % {"name": name})


def validate_score(raw, max_score):
    try:
        score = Decimal(raw)
    except InvalidOperation:
        return None, _("Score must be a number.")
    if not score.is_finite() or not 0 <= score <= max_score:
        return None, _("Score must be between 0 and %(max)s.") % {"max": number_format(max_score)}
    if score != score.quantize(CENT):
        return None, _("Score can have at most two decimal places.")
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
            number_error = _("Student number is empty.")
        elif enrollment is None:
            number_error = _("Student is not enrolled in this course.")
        elif number in seen:
            number_error = _("Student appears more than once.")

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
    rows = assessment.term_grades().order_by("enrollment_id").values_list("enrollment_id", "status", "score")
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
