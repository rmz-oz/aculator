"""How a PO score was computed (#41).

The calculation in services.py is a chain of weighted means: grade
percentages give LO scores, LOs give PO component scores within a course,
components are combined across courses by ECTS, and the PO is the plain mean
of its components. Every step is linear, so the PO score is exactly a sum
over the grades that fed it: percentage times an effective weight. Here each
score is carried as {grade: effective weight}, and the contributions are
those weights times the percentages. They add up to the score, no rounding.

The rules (which grades count, how missing evidence drops out, the weights)
must stay the same as in services.py; test_explain checks the two agree.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import F

from .models import AssessmentLOWeight, Enrollment, Grade, LOPOWeight

ZERO = Decimal(0)
ONE = Decimal(1)
HUNDRED = Decimal(100)


@dataclass
class Part:
    """One node of the explanation: a grade, an LO, a component or the PO."""

    key: tuple
    label: str
    course: str
    score: Decimal
    # Share of the PO score this node carries, 0 to 1; contributions = share * score.
    share: Decimal = ZERO
    # (child key, weight of the child inside this node, 0 to 1)
    inputs: list = field(default_factory=list)

    @property
    def contribution(self):
        return self.share * self.score


@dataclass
class Explanation:
    po_code: str
    score: Decimal
    grades: list
    los: list
    components: list

    def by_assessment(self):
        """Contributions per grade, largest first. They add up to `score`."""
        return sorted(self.grades, key=lambda p: p.contribution, reverse=True)


def _mix(parts):
    """Weighted mean of linear forms: [(form, weight)] -> form, or None."""
    total = sum((w for _, w in parts), ZERO)
    if total == ZERO:
        return None
    mixed = defaultdict(lambda: ZERO)
    for form, weight in parts:
        for leaf, w in form.items():
            mixed[leaf] += w * weight / total
    return dict(mixed)


def explain_po(student, po_code, enrollments=None):
    """Return an Explanation of the student's cross-course PO score, or None.

    `enrollments` narrows the courses the same way as
    services.student_po_scores, e.g. to what a viewer may see.
    """
    return explain_all(student, enrollments, only=po_code).get(po_code)


def explain_all(student, enrollments=None, only=None):
    """{PO code: Explanation} for every PO the student has a score in, from one set of queries."""
    if enrollments is None:
        enrollments = Enrollment.objects.all()
    enrollments = list(
        enrollments.filter(student=student).select_related("offering__course", "offering__term")
    )
    offering_of = {e.pk: e.offering_id for e in enrollments}
    enrollment_by_offering = {e.offering_id: e for e in enrollments}

    percent = {}
    grade_label = {}
    grades = Grade.objects.filter(
        # Only the partitions of these terms (#33); the terms are already loaded.
        term_id__in={e.offering.term_id for e in enrollments},
        enrollment_id__in=offering_of,
        assessment__offering_id=F("enrollment__offering_id"),
    ).select_related("assessment")
    for grade in grades:
        leaf = ("grade", grade.enrollment_id, grade.assessment_id)
        percent[leaf] = grade.score / grade.assessment.max_score * HUNDRED
        grade_label[leaf] = grade.assessment.name

    lo_inputs = defaultdict(list)
    for offering_id, assessment_id, lo_id, lo_code, weight in AssessmentLOWeight.objects.filter(
        learning_outcome__offering_id__in=offering_of.values(),
        assessment__offering_id=F("learning_outcome__offering_id"),
    ).values_list(
        "learning_outcome__offering_id", "assessment_id", "learning_outcome_id", "learning_outcome__code", "weight",
    ):
        enrollment = enrollment_by_offering[offering_id]
        leaf = ("grade", enrollment.pk, assessment_id)
        if leaf in percent:
            lo_inputs[("lo", enrollment.pk, lo_id, lo_code)].append((leaf, weight))

    # LO: weighted mean of its grades, the same skip-missing rule as services._means.
    lo_forms = {}
    for lo_key, parts in lo_inputs.items():
        form = _mix([({leaf: ONE}, w) for leaf, w in parts])
        if form is not None:
            lo_forms[lo_key] = form

    inputs_by_po = defaultdict(lambda: defaultdict(list))
    lo_key_by_id = {(k[1], k[2]): k for k in lo_forms}
    weights = LOPOWeight.objects.filter(learning_outcome__offering_id__in=offering_of.values())
    if only is not None:
        weights = weights.filter(component__program_outcome__code=only)
    for offering_id, lo_id, po, component_code, level in weights.values_list(
        "learning_outcome__offering_id", "learning_outcome_id", "component__program_outcome__code",
        "component__code", "weight",
    ):
        enrollment = enrollment_by_offering[offering_id]
        lo_key = lo_key_by_id.get((enrollment.pk, lo_id))
        if lo_key is not None:
            inputs_by_po[po][component_code].append((enrollment, lo_key, Decimal(level)))

    course_of = {e.pk: e.offering.course.code for e in enrollments}
    results = {}
    for po_code, component_inputs in inputs_by_po.items():
        explanation = _explain(po_code, component_inputs, lo_forms, percent, grade_label, course_of)
        if explanation is not None:
            results[po_code] = explanation
    return results


def _explain(po_code, component_inputs, lo_forms, percent, grade_label, course_of):

    # Component in one course, then across courses by ECTS.
    component_forms = {}
    for component_code, rows in component_inputs.items():
        per_course = defaultdict(list)
        for enrollment, lo_key, level in rows:
            per_course[enrollment].append((lo_forms[lo_key], level))
        across = []
        for enrollment, parts in per_course.items():
            form = _mix(parts)
            if form is not None:
                across.append((form, Decimal(enrollment.offering.ects)))
        form = _mix(across)
        if form is not None:
            component_forms[component_code] = form

    # PO: plain mean of the components that have evidence.
    po_form = _mix([(form, ONE) for form in component_forms.values()])
    if po_form is None:
        return None

    def value(form):
        return sum((w * percent[leaf] for leaf, w in form.items()), ZERO)

    grade_parts = [
        Part(key=leaf, label=grade_label[leaf], course=course_of[leaf[1]], score=percent[leaf], share=w)
        for leaf, w in po_form.items()
    ]

    lo_share = _lo_shares(component_forms, component_inputs, len(component_forms))
    los = [
        Part(
            key=lo_key,
            label=lo_key[3],
            course=course_of[lo_key[1]],
            score=value(form),
            share=lo_share.get(lo_key, ZERO),
            inputs=[(leaf, w) for leaf, w in form.items()],
        )
        for lo_key, form in lo_forms.items()
        if lo_share.get(lo_key, ZERO) > ZERO
    ]
    components = [
        Part(key=("component", code), label=f"{po_code}.{code}", course="", score=value(form),
             share=ONE / len(component_forms))
        for code, form in sorted(component_forms.items())
    ]

    return Explanation(
        po_code=po_code,
        score=value(po_form),
        grades=grade_parts,
        los=sorted(los, key=lambda p: (p.course, p.label)),
        components=components,
    )


def _lo_shares(component_forms, component_inputs, component_count):
    """Share of the PO score carried by each LO (sums to 1 over LOs)."""
    shares = defaultdict(lambda: ZERO)
    for component_code in component_forms:
        rows = component_inputs[component_code]
        per_course = defaultdict(list)
        for enrollment, lo_key, level in rows:
            per_course[enrollment].append((lo_key, level))
        per_course = {e: parts for e, parts in per_course.items() if sum((lv for _, lv in parts), ZERO) > ZERO}
        ects_total = sum((Decimal(e.offering.ects) for e in per_course), ZERO)
        if ects_total == ZERO:
            continue
        for enrollment, parts in per_course.items():
            level_total = sum((level for _, level in parts), ZERO)
            course_weight = Decimal(enrollment.offering.ects) / ects_total
            for lo_key, level in parts:
                shares[lo_key] += level / level_total * course_weight / component_count
    return dict(shares)
