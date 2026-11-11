from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import F

from .models import AssessmentLOWeight, Enrollment, Grade, LOPOWeight

ZERO = Decimal(0)
ONE = Decimal(1)
HUNDRED = Decimal(100)


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


def _means(groups):
    """Weighted mean of each group; groups with zero weight are left out."""
    results = {}
    for key, pairs in groups.items():
        score = weighted_mean(pairs)
        if score is not None:
            results[key] = score
    return results


def _scores(enrollments):
    """Return {enrollment_id: (lo_scores, po_scores)} in three queries.

    Missing grades and assessments with max_score=0 are excluded.
    Available contributions are normalized by their total weight.
    A missing result is omitted; an actual score of zero is retained.
    """
    offering_of = {e.pk: e.offering_id for e in enrollments}
    offerings = set(offering_of.values())

    percentages = defaultdict(dict)
    grades = Grade.objects.filter(
        enrollment_id__in=offering_of,
    ).select_related("assessment")
    for grade in grades:
        max_score = grade.assessment.max_score
        if max_score != ZERO:
            percentages[grade.enrollment_id][grade.assessment_id] = grade.score / max_score * HUNDRED

    lo_weights = defaultdict(list)
    for offering_id, assessment_id, lo_id, weight in AssessmentLOWeight.objects.filter(
        learning_outcome__offering_id__in=offerings,
        assessment__offering_id=F("learning_outcome__offering_id"),
    ).values_list("learning_outcome__offering_id", "assessment_id", "learning_outcome_id", "weight"):
        lo_weights[offering_id].append((assessment_id, lo_id, weight))

    po_weights = defaultdict(list)
    for offering_id, lo_id, po_code, level in LOPOWeight.objects.filter(
        learning_outcome__offering_id__in=offerings,
    ).values_list("learning_outcome__offering_id", "learning_outcome_id", "program_outcome__code", "weight"):
        po_weights[offering_id].append((lo_id, po_code, Decimal(level)))

    results = {}
    for enrollment_id, offering_id in offering_of.items():
        own = percentages.get(enrollment_id, {})

        per_lo = defaultdict(list)
        for assessment_id, lo_id, weight in lo_weights[offering_id]:
            if assessment_id in own:
                per_lo[lo_id].append((own[assessment_id], weight))
        los = _means(per_lo)

        per_po = defaultdict(list)
        for lo_id, po_code, level in po_weights[offering_id]:
            if lo_id in los:
                per_po[po_code].append((los[lo_id], level))

        results[enrollment_id] = (los, _means(per_po))
    return results


def lo_scores(enrollment):
    """Return {lo_id: Decimal} scores on a 0-100 scale."""
    return _scores([enrollment])[enrollment.pk][0]


def course_po_scores(enrollment):
    """Return one student's PO scores within one course offering.

    LO scores are weighted by their LO-to-PO contribution levels.
    """
    return _scores([enrollment])[enrollment.pk][1]


def student_po_scores(student):
    """Return a student's ECTS-weighted PO scores across enrollments.

    Only courses with an available score contribute to each PO.
    All enrollments are included, including repeated courses.
    """
    enrollments = list(
        Enrollment.objects.filter(student=student).select_related("offering__course"),
    )
    scores = _scores(enrollments)

    per_po = defaultdict(list)
    for enrollment in enrollments:
        ects = Decimal(enrollment.offering.course.ects)
        for po_code, score in scores[enrollment.pk][1].items():
            per_po[po_code].append((score, ects))
    return _means(per_po)


def offering_po_scores(offering):
    """Return the equal-weight mean of available student PO scores.

    Students without a score for a PO are excluded from that PO's mean.
    """
    per_po = defaultdict(list)
    for _, po_scores in _scores(list(offering.enrollments.all())).values():
        for po_code, score in po_scores.items():
            per_po[po_code].append((score, ONE))
    return _means(per_po)
