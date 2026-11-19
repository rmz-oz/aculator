from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.db import OperationalError
from django.db.models import Case, Count, IntegerField, Prefetch, Value, When
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from .access import (
    HEAD,
    STUDENT,
    can_view_student,
    grade_entry_offerings,
    report_offerings,
    role_of,
    visible_enrollments,
)
from .grade_import import grades_fingerprint, is_serialization_failure, parse_grade_files, serializable_transaction
from .models import Assessment, Grade, Term
from .services import (
    DEPARTMENT_MIN_STUDENTS,
    department_po_scores,
    display,
    scores_with_evidence_by_enrollment,
    student_po_scores,
    weighted_mean,
)

ONE = Decimal(1)
# A score backed by a single assessment is shown as thin evidence, not as a
# number (#42, decision 0006): one exam should not look as solid as five.
MIN_ASSESSMENTS_FOR_SCORE = 2


def _score_cell(score, evidence_count):
    if score is None or evidence_count == 0:
        return {"state": "empty"}
    if evidence_count < MIN_ASSESSMENTS_FOR_SCORE:
        return {"state": "low_evidence", "count": evidence_count}
    return {"state": "score", "value": display(score)}


def _po_sort_key(code):
    digits = "".join(ch for ch in code if ch.isdigit())
    return int(digits) if digits else 0


@login_required
def home(request):
    """Start page. Students go to their own profile; instructors and the head
    get the offerings they may open, newest term first, with the assessments
    an instructor can import grades for."""
    role = role_of(request.user)
    if role == STUDENT:
        return redirect("student_profile", student_id=request.user.pk)

    writable = set(grade_entry_offerings(request.user).values_list("pk", flat=True))
    assessments = Assessment.objects.annotate(graded=Count("grades")).order_by("name")
    offerings = (
        report_offerings(request.user)
        .select_related("course", "term")
        .annotate(students=Count("enrollments", distinct=True))
        .prefetch_related(Prefetch("assessments", queryset=assessments))
        .annotate(season_order=Case(
            When(term__season=Term.Season.FALL, then=Value(3)),
            When(term__season=Term.Season.SUMMER, then=Value(2)),
            default=Value(1),
            output_field=IntegerField(),
        ))
        .order_by("-term__year", "-season_order", "course__code")
    )
    courses = [{"offering": o, "can_import": o.pk in writable} for o in offerings]
    return render(request, "grading/home.html", {"nav": "home", "courses": courses})


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
    scores = scores_with_evidence_by_enrollment(enrollments)

    lo_values = {lo.pk: [] for lo in los}
    po_values = {}
    rows = []
    for enrollment in enrollments:
        lo_scores, po_scores, lo_counts, po_counts = scores[enrollment.pk]
        # The class average uses only the scores the table shows as numbers;
        # a single assessment is too thin to pull the average around.
        for lo in los:
            score = lo_scores.get(lo.pk)
            if score is not None and lo_counts.get(lo.pk, 0) >= MIN_ASSESSMENTS_FOR_SCORE:
                lo_values[lo.pk].append(score)
        for code, score in po_scores.items():
            values = po_values.setdefault(code, [])
            if po_counts.get(code, 0) >= MIN_ASSESSMENTS_FOR_SCORE:
                values.append(score)
        rows.append({
            "student": enrollment.student,
            "lo_cells": [_score_cell(lo_scores.get(lo.pk), lo_counts.get(lo.pk, 0)) for lo in los],
            "po_scores": po_scores,
            "po_counts": po_counts,
        })

    po_codes = sorted(po_values, key=_po_sort_key)
    for row in rows:
        row["po_cells"] = [
            _score_cell(row["po_scores"].get(code), row["po_counts"].get(code, 0)) for code in po_codes
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
        "can_import": grade_entry_offerings(request.user).filter(pk=offering.pk).exists(),
        "assessments": offering.assessments.order_by("name"),
        "nav": "home",
    })


@login_required
def student_profile(request, student_id):
    """A student's cross-course PO scores next to the anonymous department average (#14).

    Open to the student themselves, their instructors and the head
    (grading.access.can_view_student); everyone else gets 404. An instructor
    sees the scores from the courses they teach only, not the student's other
    courses (grading.access.visible_enrollments).
    """
    student = get_object_or_404(get_user_model(), pk=student_id)
    if not can_view_student(request.user, student):
        raise Http404

    own_profile = student.pk == request.user.pk
    # The student reads all their own courses, even if they also teach one.
    enrollments = None if own_profile else visible_enrollments(request.user)
    own = student_po_scores(student, enrollments)
    department = department_po_scores()
    po_codes = sorted(set(own) | set(department), key=_po_sort_key)

    rows = [
        {
            "code": code,
            "own": display(own.get(code)),
            "department": display(department.get(code)),
            # Compare what is shown: the view and the service round differently
            # in the last digits, and 85.0 must not read as below 85.0.
            "below_average": (
                code in own and code in department and display(own[code]) < display(department[code])
            ),
        }
        for code in po_codes
    ]

    return render(request, "grading/student_profile.html", {
        "student": student,
        "rows": rows,
        "own_profile": own_profile,
        "all_courses": own_profile or role_of(request.user) == HEAD,
        "min_students": DEPARTMENT_MIN_STUDENTS,
        "nav": "home" if own_profile else None,
    })


PREVIEW_SALT = "grade-import-preview"
PREVIEW_MAX_AGE = 15 * 60


@login_required
def grade_import(request, assessment_id):
    """Import grades for one assessment from one or more CSV files (#13).

    "Import" saves the files right away. "Preview" saves nothing; it lists
    the changes and the enrolled students missing from every file, and the
    instructor can mark those absent before confirming. Each POST runs in one
    SERIALIZABLE transaction (docs/decisions/0008), so any error saves
    nothing. Only the offering's instructors get past the 404.
    """
    if request.method != "POST":
        return _import_page(request, _gradable_assessment(request, assessment_id))

    try:
        with serializable_transaction():
            assessment = _gradable_assessment(request, assessment_id)
            if request.POST.get("action") == "confirm":
                return _confirm_preview(request, assessment)
            return _upload(request, assessment)
    except OperationalError as error:
        if not is_serialization_failure(error):
            raise
    return _import_page(
        request,
        _gradable_assessment(request, assessment_id),
        errors=["Someone changed these grades at the same time, so nothing was saved. Choose the files again."],
        status=409,
    )


def _gradable_assessment(request, assessment_id):
    return get_object_or_404(
        Assessment.objects.select_related("offering__course", "offering__term"),
        pk=assessment_id,
        offering__in=grade_entry_offerings(request.user),
    )


def _import_page(request, assessment, status=200, **context):
    return render(
        request, "grading/grade_import.html", {"assessment": assessment, "nav": "home", **context}, status=status,
    )


def _upload(request, assessment):
    files = request.FILES.getlist("csv_file")
    if not files:
        return _import_page(request, assessment, errors=["Choose at least one CSV file."])

    enrollments = {e.student.username: e for e in assessment.offering.enrollments.select_related("student")}
    parsed = parse_grade_files(files, assessment, enrollments)
    if parsed.errors:
        return _import_page(request, assessment, errors=parsed.errors)

    if request.POST.get("action") == "preview":
        return _preview(request, assessment, enrollments, parsed)

    _save_scores(assessment, [(e.pk, score) for e, score in parsed.rows])
    return _import_page(request, assessment, saved_count=len(parsed.rows))


def _preview(request, assessment, enrollments, parsed):
    existing = {g.enrollment_id: g for g in assessment.grades.all()}
    changes = []
    for enrollment, score in parsed.rows:
        old = existing.get(enrollment.pk)
        if old is not None and (old.status, old.score) != (Grade.Status.GRADED, score):
            shown = "absent" if old.status == Grade.Status.ABSENT else old.score
            changes.append(f"{enrollment.student.username}: {shown} to {score}")

    missing = sorted(enrollments.keys() - parsed.locations.keys())
    # A student who already has a grade keeps it; only the rest can be marked absent.
    absent_candidates = [n for n in missing if enrollments[n].pk not in existing]
    kept = [n for n in missing if enrollments[n].pk in existing]

    token = signing.dumps({
        "assessment_id": assessment.pk,
        "user_id": request.user.pk,
        "max_score": str(assessment.max_score),
        "enrollment_ids": sorted(e.pk for e in enrollments.values()),
        "grades": grades_fingerprint(assessment),
        "scores": [[e.pk, str(score)] for e, score in parsed.rows],
        "absent_candidates": {n: enrollments[n].pk for n in absent_candidates},
    }, salt=PREVIEW_SALT)

    return _import_page(
        request, assessment,
        preview_token=token,
        preview_count=len(parsed.rows),
        changes=changes,
        absent_candidates=absent_candidates,
        kept=kept,
    )


def _confirm_preview(request, assessment):
    try:
        preview = signing.loads(request.POST.get("preview_token", ""), salt=PREVIEW_SALT, max_age=PREVIEW_MAX_AGE)
    except signing.BadSignature:
        preview = None

    if preview is None or preview["assessment_id"] != assessment.pk or preview["user_id"] != request.user.pk:
        error = "The preview is invalid or has expired. Preview the files again."
    elif preview["max_score"] != str(assessment.max_score):
        error = "The maximum score of this assessment changed. Preview the files again."
    elif preview["enrollment_ids"] != sorted(assessment.offering.enrollments.values_list("pk", flat=True)):
        error = "Enrollments in this course changed. Preview the files again."
    elif preview["grades"] != grades_fingerprint(assessment):
        error = "Grades for this assessment changed after the preview, or it was already saved. Preview again."
    elif not set(request.POST.getlist("absent_students")) <= preview["absent_candidates"].keys():
        error = "Only students suggested in the preview can be marked absent."
    else:
        error = None
    if error:
        return _import_page(request, assessment, errors=[error])

    scores = [(enrollment_id, Decimal(score)) for enrollment_id, score in preview["scores"]]
    _save_scores(assessment, scores)
    absent = sorted(set(request.POST.getlist("absent_students")))
    for number in absent:
        # create(), not bulk_create(): the post_save signal refreshes the report views.
        Grade.objects.create(
            assessment=assessment,
            enrollment_id=preview["absent_candidates"][number],
            status=Grade.Status.ABSENT,
            score=0,
        )
    return _import_page(request, assessment, saved_count=len(scores), absent_count=len(absent))


def _save_scores(assessment, scores):
    for enrollment_id, score in scores:
        Grade.objects.update_or_create(
            assessment=assessment,
            enrollment_id=enrollment_id,
            defaults={"score": score, "status": Grade.Status.GRADED},
        )
