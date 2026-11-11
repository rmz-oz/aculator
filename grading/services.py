from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import F

from .models import (
    AssessmentLOWeight,
    Enrollment,
    Grade,
    LOPOWeight,
    ProgramOutcome,
)

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
    """Return weighted group means, omitting groups without evidence."""
    results = {}
    for key, pairs in groups.items():
        score = weighted_mean(pairs)
        if score is not None:
            results[key] = score
    return results


def _component_results(enrollments):
    """Return {enrollment_id: (LO scores, component scores)}."""
    offering_of = {e.pk: e.offering_id for e in enrollments}
    offerings = set(offering_of.values())

    percentages = defaultdict(dict)
    grades = Grade.objects.filter(
        enrollment_id__in=offering_of,
        assessment__offering_id=F("enrollment__offering_id"),
    ).select_related("assessment")

    for grade in grades:
        maximum = grade.assessment.max_score
        if maximum > ZERO:
            percentages[grade.enrollment_id][grade.assessment_id] = (
                grade.score / maximum * HUNDRED
            )

    lo_weights = defaultdict(list)
    rows = AssessmentLOWeight.objects.filter(
        learning_outcome__offering_id__in=offerings,
        assessment__offering_id=F("learning_outcome__offering_id"),
    ).values_list(
        "learning_outcome__offering_id",
        "assessment_id",
        "learning_outcome_id",
        "weight",
    )
    for offering_id, assessment_id, lo_id, weight in rows:
        lo_weights[offering_id].append((assessment_id, lo_id, weight))

    component_weights = defaultdict(list)
    rows = LOPOWeight.objects.filter(
        learning_outcome__offering_id__in=offerings,
    ).values_list(
        "learning_outcome__offering_id",
        "learning_outcome_id",
        "component__program_outcome__code",
        "component__code",
        "weight",
    )
    for offering_id, lo_id, po_code, component_code, level in rows:
        key = (po_code, component_code)
        component_weights[offering_id].append(
            (lo_id, key, Decimal(level)),
        )

    results = {}
    for enrollment_id, offering_id in offering_of.items():
        own = percentages.get(enrollment_id, {})

        per_lo = defaultdict(list)
        for assessment_id, lo_id, weight in lo_weights[offering_id]:
            if assessment_id in own:
                per_lo[lo_id].append((own[assessment_id], weight))
        los = _means(per_lo)

        per_component = defaultdict(list)
        for lo_id, key, level in component_weights[offering_id]:
            if lo_id in los:
                per_component[key].append((los[lo_id], level))

        results[enrollment_id] = (los, _means(per_component))

    return results


def _po_display_scores(components):
    """Return equal-weight component means for display only."""
    groups = defaultdict(list)
    for (po_code, _), score in components.items():
        groups[po_code].append((score, ONE))
    return _means(groups)


def scores_by_enrollment(enrollments):
    """Return {enrollment_id: (lo_scores, po_scores)}; the course report page reads this."""
    results = {}
    for enrollment_id, (los, components) in _component_results(
        enrollments,
    ).items():
        results[enrollment_id] = (los, _po_display_scores(components))
    return results


def lo_scores(enrollment):
    """Return {LO id: score}, omitting LOs without evidence."""
    return _component_results([enrollment])[enrollment.pk][0]


def course_component_scores(enrollment):
    """Return {(PO code, component code): score} for one enrollment."""
    return _component_results([enrollment])[enrollment.pk][1]


def course_po_scores(enrollment):
    """Return display-only PO means within one course offering."""
    return _po_display_scores(course_component_scores(enrollment))


def student_component_scores(student):
    """Combine each component across courses using ECTS weights."""
    enrollments = list(
        Enrollment.objects.filter(student=student).select_related(
            "offering__course",
        ),
    )
    results = _component_results(enrollments)

    groups = defaultdict(list)
    for enrollment in enrollments:
        ects = Decimal(enrollment.offering.course.ects)
        for key, score in results[enrollment.pk][1].items():
            groups[key].append((score, ects))

    return _means(groups)


def student_po_scores(student):
    """Return display-only means of the student's component scores."""
    return _po_display_scores(student_component_scores(student))


def offering_component_scores(offering):
    """Return equal-weight student means per component."""
    results = _component_results(list(offering.enrollments.all()))

    groups = defaultdict(list)
    for _, components in results.values():
        for key, score in components.items():
            groups[key].append((score, ONE))

    return _means(groups)


def offering_po_scores(offering):
    """Return display-only means of the offering's component scores."""
    return _po_display_scores(offering_component_scores(offering))


def po_report(component_scores, threshold):
    """Evaluate every defined component using unrounded scores.

    Missing evidence has score=None and blocks PO attainment.
    A PO without defined components is not met.
    """
    threshold = Decimal(str(threshold))
    if not threshold.is_finite() or not ZERO <= threshold <= HUNDRED:
        raise ValueError("Threshold must be between 0 and 100.")

    report = {}
    outcomes = ProgramOutcome.objects.prefetch_related("components")

    for po in outcomes:
        components = {}
        available = []

        for component in po.components.all():
            score = component_scores.get((po.code, component.code))
            met = score is not None and score >= threshold

            if score is None:
                status = "no evidence"
            elif met:
                status = "met"
            else:
                status = "not met"

            components[component.code] = {
                "description": component.description,
                "score": score,
                "status": status,
                "met": met,
            }

            if score is not None:
                available.append((score, ONE))

        report[po.code] = {
            "score": weighted_mean(available),
            "met": bool(components) and all(
                item["met"] for item in components.values()
            ),
            "components": components,
        }

    return report


def course_po_report(enrollment, threshold):
    """Return component evidence and PO attainment for an enrollment."""
    return po_report(course_component_scores(enrollment), threshold)


def student_po_report(student, threshold):
    """Return component evidence and PO attainment across courses."""
    return po_report(student_component_scores(student), threshold)
