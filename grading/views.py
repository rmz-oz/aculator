from decimal import Decimal

from django.shortcuts import get_object_or_404, render

from .access import report_offerings
from .services import display, scores_with_evidence_by_enrollment, weighted_mean

ONE = Decimal(1)
MIN_ASSESSMENTS_FOR_SCORE = 2

def _score_cell(score, evidence_count):
    if evidence_count == 0:
        return {"state": "empty"}
    if evidence_count < MIN_ASSESSMENTS_FOR_SCORE:
        return {"state": "low_evidence"}
    return {"state": "score", "value": display(score)}


def _po_sort_key(code):
    digits = "".join(ch for ch in code if ch.isdigit())
    return int(digits) if digits else 0


def course_report(request, offering_id):
    """Instructor view of one offering: per-student and class LO/PO scores.

    Only the head of department and the offering's instructors may open it
    (grading.access.report_offerings); everyone else gets 404, so the page does
    not even confirm that the offering exists.
    """
    offering = get_object_or_404(
        report_offerings(request.user).select_related("course", "term"),
        pk=offering_id,
    )
    los = list(offering.learning_outcomes.all())
    enrollments = list(
        offering.enrollments.select_related("student").order_by(
            "student__last_name", "student__first_name", "student__username",
        )
    )

    # One batched call for the whole class, not one query per student.


    scores = scores_with_evidence_by_enrollment(enrollments)

    lo_values = {lo.pk: [] for lo in los}
    po_values = {}
    rows = []
    for enrollment in enrollments:
        lo_scores, po_scores, lo_counts, po_counts = scores[enrollment.pk]
        for lo in los:
            score = lo_scores.get(lo.pk)
            if score is not None:
                lo_values[lo.pk].append(score)
        for code, score in po_scores.items():
            po_values.setdefault(code, []).append(score)
        rows.append({
            "student": enrollment.student,
            "lo_cells": [
                _score_cell(lo_scores.get(lo.pk), lo_counts.get(lo.pk, 0))
                for lo in los
            ],
            "po_scores": po_scores,
            "po_counts": po_counts,
        })

    po_codes = sorted(po_values, key=_po_sort_key)
    for row in rows:
        row["po_cells"] = [
            _score_cell(row["po_scores"].get(code), row["po_counts"].get(code, 0))
            for code in po_codes
        ]

    lo_class_avg = [
        display(weighted_mean([(v, ONE) for v in lo_values[lo.pk]]))
        for lo in los
    ]
    po_class_avg = [
        display(weighted_mean([(v, ONE) for v in po_values[code]]))
        for code in po_codes
    ]

    return render(request, "grading/course_report.html", {
        "offering": offering,
        "los": los,
        "po_codes": po_codes,
        "rows": rows,
        "lo_class_avg": lo_class_avg,
        "po_class_avg": po_class_avg,
    })
