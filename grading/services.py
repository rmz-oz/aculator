from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from .models import AssessmentLOWeight, Enrollment, LOPOWeight


ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")


def weighted_mean(pairs):
    """Return the weighted mean, or None when total weight is zero."""
    numerator = ZERO
    denominator = ZERO

    for value, weight in pairs:
        numerator += value * weight
        denominator += weight

    if denominator == ZERO:
        return None

    return numerator / denominator


def display(value, places="0.1"):
    """Round only for display; preserve None for unavailable scores."""
    if value is None:
        return None

    return value.quantize(
        Decimal(places),
        rounding=ROUND_HALF_UP,
    )


def lo_scores(enrollment):
    """Return {lo_id: Decimal} scores on a 0–100 scale.

    Missing grades and assessments with max_score=0 are excluded.
    Available contributions are normalized by their total weight.
    A missing result is omitted; an actual score of zero is retained.
    """
    grades = {
        grade.assessment_id: grade
        for grade in enrollment.grades.select_related("assessment")
    }

    weights = AssessmentLOWeight.objects.filter(
        learning_outcome__offering_id=enrollment.offering_id,
        assessment__offering_id=enrollment.offering_id,
    )

    per_lo = defaultdict(list)

    for weight in weights:
        grade = grades.get(weight.assessment_id)

        if grade is None or grade.assessment.max_score == ZERO:
            continue

        percentage = (
            grade.score / grade.assessment.max_score * HUNDRED
        )
        per_lo[weight.learning_outcome_id].append(
            (percentage, weight.weight)
        )

    results = {}
    for lo_id, pairs in per_lo.items():
        score = weighted_mean(pairs)
        if score is not None:
            results[lo_id] = score

    return results


def course_po_scores(enrollment):
    """Return one student's PO scores within one course offering.

    LO scores are weighted by their LO-to-PO contribution levels.
    """
    los = lo_scores(enrollment)

    weights = LOPOWeight.objects.filter(
        learning_outcome_id__in=los,
    ).select_related("program_outcome")

    per_po = defaultdict(list)

    for weight in weights:
        per_po[weight.program_outcome.code].append(
            (
                los[weight.learning_outcome_id],
                Decimal(weight.weight),
            )
        )

    results = {}
    for po_code, pairs in per_po.items():
        score = weighted_mean(pairs)
        if score is not None:
            results[po_code] = score

    return results


def student_po_scores(student):
    """Return a student's ECTS-weighted PO scores across enrollments.

    Only courses with an available score contribute to each PO.
    All enrollments are included, including repeated courses.
    """
    enrollments = Enrollment.objects.filter(
        student=student,
    ).select_related("offering__course")

    per_po = defaultdict(list)

    for enrollment in enrollments:
        ects = Decimal(enrollment.offering.course.ects)

        for po_code, score in course_po_scores(enrollment).items():
            per_po[po_code].append((score, ects))

    results = {}
    for po_code, pairs in per_po.items():
        score = weighted_mean(pairs)
        if score is not None:
            results[po_code] = score

    return results


def offering_po_scores(offering):
    """Return the equal-weight mean of available student PO scores.

    Students without a score for a PO are excluded from that PO's mean.
    """
    per_po = defaultdict(list)

    for enrollment in offering.enrollments.all():
        for po_code, score in course_po_scores(enrollment).items():
            per_po[po_code].append((score, ONE))

    results = {}
    for po_code, pairs in per_po.items():
        score = weighted_mean(pairs)
        if score is not None:
            results[po_code] = score

    return results