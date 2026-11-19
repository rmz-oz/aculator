from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from .access import can_view_student, report_offerings
from .services import department_po_scores, display, scores_by_enrollment, student_po_scores, weighted_mean

ONE = Decimal(1)


def _po_sort_key(code):
    digits = "".join(ch for ch in code if ch.isdigit())
    return int(digits) if digits else 0


@login_required
def course_report(request, offering_id):
    """Instructor view of one offering: per-student and class LO/PO scores.

    Only the head of department and the offering's instructors may open it
    (grading.access.report_offerings); everyone else gets 404, so the page does
    not even confirm that the offering exists. A logged out visitor is sent to
    the login page instead (#77).
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
    scores = scores_by_enrollment(enrollments)

    lo_values = {lo.pk: [] for lo in los}
    po_values = {}
    rows = []
    for enrollment in enrollments:
        lo_scores, po_scores = scores[enrollment.pk]
        for lo in los:
            score = lo_scores.get(lo.pk)
            if score is not None:
                lo_values[lo.pk].append(score)
        for code, score in po_scores.items():
            po_values.setdefault(code, []).append(score)
        rows.append({
            "student": enrollment.student,
            "lo_cells": [display(lo_scores.get(lo.pk)) for lo in los],
            "po_scores": po_scores,
        })

    po_codes = sorted(po_values, key=_po_sort_key)
    for row in rows:
        row["po_cells"] = [display(row["po_scores"].get(code)) for code in po_codes]

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


@login_required
def student_profile(request, student_id):
    """A student's cross-course PO scores next to the anonymous department average (#14).

    Open to the student themselves, their instructors and the head
    (grading.access.can_view_student); everyone else gets 404.
    """
    student = get_object_or_404(get_user_model(), pk=student_id)
    if not can_view_student(request.user, student):
        raise Http404

    own = student_po_scores(student)
    department = department_po_scores()
    po_codes = sorted(set(own) | set(department), key=_po_sort_key)

    rows = [
        {
            "code": code,
            "own": display(own.get(code)),
            "department": display(department.get(code)),
            "below_average": (
                code in own and code in department and own[code] < department[code]
            ),
        }
        for code in po_codes
    ]

    return render(request, "grading/student_profile.html", {
        "student": student,
        "rows": rows,
    })
