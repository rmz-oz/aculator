from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from django.db import connection
from django.db.models import F

from .models import (
    AssessmentLOWeight,
    CourseOffering,
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


SEASON_ORDER = {"spring": 1, "summer": 2, "fall": 3}


def attempt_order(offering):
    """Sort key of an attempt: later terms last (spring, summer, fall within a year)."""
    return (offering.term.year, SEASON_ORDER[offering.term.season], offering.pk)


def counting_enrollments(enrollments, has_scores):
    """Pks of the attempts that count across courses (#104, decision 0011).

    A course taken more than once counts once: its latest attempt with scores,
    as the regulation counts the last grade. An attempt without scores (a
    withdrawal, a retake not graded yet) leaves the earlier one in place.
    Same rule as refresh_scores() in migration 0014.
    """
    latest = {}
    for enrollment in enrollments:
        if not has_scores(enrollment):
            continue
        key = (enrollment.student_id, enrollment.offering.course_id)
        if key not in latest or attempt_order(enrollment.offering) > attempt_order(latest[key].offering):
            latest[key] = enrollment
    return {enrollment.pk for enrollment in latest.values()}


def counting_enrollment_ids(student):
    """Pks of the student's attempts that count, decided over all their courses (#104).

    Decided over every enrollment, not the ones a viewer may see: an instructor
    who taught only the failed attempt must not see it counted.
    """
    enrollments = list(
        Enrollment.objects.filter(student=student).select_related("offering__term")
    )
    courses = [e.offering.course_id for e in enrollments]
    if len(courses) == len(set(courses)):
        return {e.pk for e in enrollments}
    results = _component_results(enrollments)
    return counting_enrollments(enrollments, lambda e: bool(results[e.pk][1]))


def replaced_grades(grades):
    """{(enrollment id, assessment id)} left out because of a makeup (#105).

    A graded makeup leaves out the assessment it replaces. A makeup the student
    is marked absent from is no attempt: it is left out itself and the replaced
    grade stays. Same rule as refresh_scores() in migration 0014.
    """
    left_out = set()
    for grade in grades:
        if grade.assessment.replaces_id is None:
            continue
        if grade.status == Grade.Status.GRADED:
            left_out.add((grade.enrollment_id, grade.assessment.replaces_id))
        else:
            left_out.add((grade.enrollment_id, grade.assessment_id))
    return left_out


def _means(groups):
    """Return weighted group means, omitting groups without evidence."""
    results = {}
    for key, pairs in groups.items():
        score = weighted_mean(pairs)
        if score is not None:
            results[key] = score
    return results


def _component_results(enrollments):
    """Return LO scores, component scores, and LO and PO evidence counts by enrollment."""
    offering_of = {e.pk: e.offering_id for e in enrollments}
    offerings = set(offering_of.values())

    percentages = defaultdict(dict)
    # Grades are partitioned by term (#33). Naming the terms lets PostgreSQL
    # plan and read only their partitions; without it every partition is
    # planned (docs/partitioning.md). Costs one small query.
    terms = set(CourseOffering.objects.filter(pk__in=offerings).values_list("term_id", flat=True))
    grades = Grade.objects.filter(
        term_id__in=terms,
        enrollment_id__in=offering_of,
        assessment__offering_id=F("enrollment__offering_id"),
    ).select_related("assessment")

    # Absent grades are stored as 0 and count. max_score > 0 is a database
    # constraint, so the division is safe.
    grades = list(grades)
    for grade in grades:
        percentages[grade.enrollment_id][grade.assessment_id] = (
            grade.score / grade.assessment.max_score * HUNDRED
        )
    for enrollment_id, assessment_id in replaced_grades(grades):
        percentages[enrollment_id].pop(assessment_id, None)

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
        lo_assessment_ids = defaultdict(set)

        for assessment_id, lo_id, weight in lo_weights[offering_id]:
            if assessment_id in own and weight > ZERO:
                per_lo[lo_id].append((own[assessment_id], weight))
                lo_assessment_ids[lo_id].add(assessment_id)

        los = _means(per_lo)

        per_component = defaultdict(list)
        po_assessment_ids = defaultdict(set)

        for lo_id, key, level in component_weights[offering_id]:
            if lo_id in los:
                per_component[key].append((los[lo_id], level))
                po_code, _ = key
                po_assessment_ids[po_code].update(lo_assessment_ids[lo_id])

        results[enrollment_id] = (
            los,
            _means(per_component),
            {lo_id: len(ids) for lo_id, ids in lo_assessment_ids.items()},
            {po_code: len(ids) for po_code, ids in po_assessment_ids.items()},
        )

    return results


def _po_display_scores(components):
    """Return equal-weight component means for display only."""
    groups = defaultdict(list)
    for (po_code, _), score in components.items():
        groups[po_code].append((score, ONE))
    return _means(groups)


def scores_with_evidence_by_enrollment(enrollments):
    """Return LO and PO scores and their evidence counts by enrollment."""
    return {
        enrollment_id: (los, _po_display_scores(components), lo_counts, po_counts)
        for enrollment_id, (los, components, lo_counts, po_counts)
        in _component_results(enrollments).items()
    }


def scores_by_enrollment(enrollments):
    """Return LO and PO scores by enrollment."""
    return {
        enrollment_id: (los, pos)
        for enrollment_id, (los, pos, _, _)
        in scores_with_evidence_by_enrollment(enrollments).items()
    }


def lo_scores(enrollment):
    """Return {LO id: score}, omitting LOs without evidence."""
    return _component_results([enrollment])[enrollment.pk][0]


def course_component_scores(enrollment):
    """Return {(PO code, component code): score} for one enrollment."""
    return _component_results([enrollment])[enrollment.pk][1]


def course_po_scores(enrollment):
    """Return display-only PO means within one course offering."""
    return _po_display_scores(course_component_scores(enrollment))


def student_component_scores(student, enrollments=None):
    """Combine each component across courses using ECTS weights.

    `enrollments` narrows the courses, e.g. to the ones a viewer may see;
    by default every course the student has taken counts.
    """
    every_course = enrollments is None
    if every_course:
        enrollments = Enrollment.objects.all()
    enrollments = list(
        enrollments.filter(student=student).select_related(
            "offering__course", "offering__term",
        ),
    )
    results = _component_results(enrollments)
    if every_course:
        counting = counting_enrollments(enrollments, lambda e: bool(results[e.pk][1]))
    else:
        counting = counting_enrollment_ids(student)

    groups = defaultdict(list)
    for enrollment in enrollments:
        if enrollment.pk not in counting:
            continue
        ects = Decimal(enrollment.offering.ects)
        for key, score in results[enrollment.pk][1].items():
            groups[key].append((score, ects))

    return _means(groups)


def student_po_scores(student, enrollments=None):
    """Return display-only means of the student's component scores."""
    return _po_display_scores(student_component_scores(student, enrollments))


def offering_component_scores(offering):
    """Return equal-weight student means per component."""
    results = _component_results(list(offering.enrollments.all()))

    groups = defaultdict(list)
    for _, components, _, _ in results.values():
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


# A mean of one or two students is not anonymous: with two, either of them
# can work out the other's exact score from their own. Below this many
# students a PO gets no department figure.
DEPARTMENT_MIN_STUDENTS = 5


def department_po_scores(min_students=DEPARTMENT_MIN_STUDENTS):
    """Mean of every student's cross-course score per PO, keyed by PO code.

    Reads the department_po_means materialized view (#9, #79), one row per
    PO, instead of recomputing every grade in the department on each profile
    view. Only the per-PO mean leaves this function, and only for POs with at
    least `min_students` scored students, so the comparison stays anonymous (#14).
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT po.code, d.score
            FROM department_po_means d
            JOIN grading_programoutcome po ON po.id = d.program_outcome_id
            WHERE d.students >= %s
            """,
            [min_students],
        )
        return {code: score for code, score in cursor.fetchall()}

def report_scores_from_views(enrollments):
    """Read report scores from materialized views and count graded evidence."""
    enrollments = list(enrollments)
    if not enrollments:
        return {}

    offering_of = {e.pk: e.offering_id for e in enrollments}
    enrollment_by_student_offering = {
        (e.student_id, e.offering_id): e.pk for e in enrollments
    }
    offering_ids = set(offering_of.values())

    results = {
        e.pk: ({}, {}, {}, {}) for e in enrollments
    }

    # LO scores from materialized view.
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT student_id, offering_id, learning_outcome_id, score
            FROM student_lo_scores
            WHERE offering_id = ANY(%s)
            """,
            [list(offering_ids)],
        )
        for student_id, offering_id, lo_id, score in cursor.fetchall():
            enrollment_id = enrollment_by_student_offering.get(
                (student_id, offering_id)
            )
            if enrollment_id is not None:
                results[enrollment_id][0][lo_id] = score

    # PO scores from materialized view.
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT s.student_id, s.offering_id, p.code, s.score
            FROM course_po_scores s
            JOIN grading_programoutcome p
              ON p.id = s.program_outcome_id
            WHERE s.offering_id = ANY(%s)
            """,
            [list(offering_ids)],
        )
        for student_id, offering_id, code, score in cursor.fetchall():
            enrollment_id = enrollment_by_student_offering.get(
                (student_id, offering_id)
            )
            if enrollment_id is not None:
                results[enrollment_id][1][code] = score

    # Count distinct graded assessments per LO and PO.
    terms = set(
        CourseOffering.objects.filter(
            pk__in=offering_ids
        ).values_list("term_id", flat=True)
    )

    grade_assessments = defaultdict(set)
    replaced = set()
    for enrollment_id, assessment_id, replaces_id, status in Grade.objects.filter(
        term_id__in=terms,
        enrollment_id__in=offering_of,
        assessment__offering_id=F("enrollment__offering_id"),
    ).values_list("enrollment_id", "assessment_id", "assessment__replaces_id", "status"):
        grade_assessments[enrollment_id].add(assessment_id)
        if replaces_id is not None:
            replaced.add((enrollment_id, replaces_id if status == Grade.Status.GRADED else assessment_id))
    # A makeup's replaced grade is not evidence (#105), as in refresh_scores().
    for enrollment_id, assessment_id in replaced:
        grade_assessments[enrollment_id].discard(assessment_id)

    lo_assessments = defaultdict(lambda: defaultdict(set))
    for offering_id, assessment_id, lo_id in AssessmentLOWeight.objects.filter(
        learning_outcome__offering_id__in=offering_ids,
        assessment__offering_id=F("learning_outcome__offering_id"),
        weight__gt=0,
    ).values_list(
        "learning_outcome__offering_id",
        "assessment_id",
        "learning_outcome_id",
    ):
        lo_assessments[offering_id][lo_id].add(assessment_id)

    po_los = defaultdict(lambda: defaultdict(set))
    for offering_id, lo_id, po_code in LOPOWeight.objects.filter(
        learning_outcome__offering_id__in=offering_ids,
    ).values_list(
        "learning_outcome__offering_id",
        "learning_outcome_id",
        "component__program_outcome__code",
    ):
        po_los[offering_id][po_code].add(lo_id)

    for enrollment_id, offering_id in offering_of.items():
        graded = grade_assessments[enrollment_id]
        lo_counts = results[enrollment_id][2]
        po_counts = results[enrollment_id][3]

        for lo_id, assessment_ids in lo_assessments[offering_id].items():
            count = len(graded & assessment_ids)
            if count:
                lo_counts[lo_id] = count

        for po_code, lo_ids in po_los[offering_id].items():
            evidence = set()
            for lo_id in lo_ids:
                evidence.update(
                    graded & lo_assessments[offering_id][lo_id]
                )
            if evidence:
                po_counts[po_code] = len(evidence)

    return results
