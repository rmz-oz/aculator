import json
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.db import OperationalError
from django.db.models import Case, Count, IntegerField, Prefetch, Value, When
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .access import (
    HEAD,
    STUDENT,
    can_view_student,
    grade_entry_offerings,
    report_offerings,
    role_of,
    visible_enrollments,
)
from .demo import demo_user
from .explain import explain_all, explain_po
from .grade_history import grade_change_actor
from .grade_import import (
    grades_fingerprint,
    is_serialization_failure,
    parse_grade_files,
    serializable_transaction,
    validate_pasted_grades,
)
from .models import Assessment, Grade, Term
from .services import (
    DEPARTMENT_MIN_STUDENTS,
    department_po_scores,
    display,
    po_report,
    scores_with_evidence_by_enrollment,
    student_component_scores,
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
    # One group per term, newest first. The newest is open; earlier terms fold
    # away so an instructor with years of courses does not scroll past them all.
    terms = []
    for o in offerings:
        if not terms or terms[-1]["term"] != o.term:
            terms.append({"term": o.term, "courses": []})
        terms[-1]["courses"].append({"offering": o, "can_import": o.pk in writable})
    return render(request, "grading/home.html", {"nav": "home", "terms": terms})


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
    student, own_profile, enrollments = _profile_scope(request, student_id)
    from_report = _from_report(request, student)
    components = student_component_scores(student, enrollments)
    own = student_po_scores(student, enrollments)
    report = po_report(components, settings.PO_TARGET)
    target = Decimal(settings.PO_TARGET)
    department = department_po_scores()
    po_codes = sorted(set(own) | set(department), key=_po_sort_key)

    explanations = explain_all(student, enrollments)
    rows = []
    for code in po_codes:
        shown = display(own.get(code))
        mean = display(department.get(code))
        parts = report.get(code, {}).get("components", {})
        below = sorted(f"{code}.{c}" for c, item in parts.items() if item["status"] == "not met")
        missing = sorted(f"{code}.{c}" for c, item in parts.items() if item["status"] == "no evidence")
        explanation = explanations.get(code)
        evidence = len(explanation.grades) if explanation else 0
        thin = shown is not None and evidence < MIN_ASSESSMENTS_FOR_SCORE
        rows.append({
            "code": code,
            "own": shown,
            "department": mean,
            # Red means below the PO target: a component under it. Below the
            # department mean is only a comparison and stays black. Compare
            # what is shown: 85.0 must not read as below 85.0.
            # One assessment is too thin to judge against the target or the mean (#42).
            "thin": thin,
            "evidence": evidence,
            "below_target": bool(below) and not thin,
            "below_average": not thin and shown is not None and mean is not None and shown < mean,
            "components_below": below,
            "components_missing": missing if shown is not None else [],
            "ring": _ring(explanation) if explanation and not thin else None,
        })

    return render(request, "grading/student_profile.html", {
        "student": student,
        "rows": rows,
        "target": display(target, "1"),
        "own_profile": own_profile,
        "all_courses": own_profile or role_of(request.user) == HEAD,
        "min_students": DEPARTMENT_MIN_STUDENTS,
        "from_report": from_report,
        "nav": "home" if own_profile else None,
    })


def _from_report(request, student):
    """The class report a profile was opened from (?from=<offering>), if the
    viewer may open that report and the student is in it; otherwise None, so a
    hand-edited link shows nothing extra."""
    try:
        offering_id = int(request.GET.get("from", ""))
    except ValueError:  # also "²", which str.isdigit() lets through
        return None
    return (
        report_offerings(request.user)
        .select_related("course", "term")
        .filter(pk=offering_id, enrollments__student=student)
        .first()
    )


def _profile_scope(request, student_id):
    """The student, whether it is the viewer's own profile, and the enrollments to count.

    The student reads all their own courses, even if they also teach one; an
    instructor only the courses they teach (grading.access.visible_enrollments).
    """
    student = get_object_or_404(get_user_model(), pk=student_id)
    if not can_view_student(request.user, student):
        raise Http404
    own_profile = student.pk == request.user.pk
    return student, own_profile, None if own_profile else visible_enrollments(request.user)


def _ring(explanation):
    """Sunburst data for the ring next to a PO: courses inside, assessments outside, the rest to 100 empty."""
    courses = {}
    for part in explanation.by_assessment():
        courses.setdefault(part.course, []).append({
            "name": part.label,
            "value": float(part.contribution),
            "label": f"{part.course} {part.label}: {display(part.contribution)}",
        })
    data = [
        {"name": course, "children": children, "value": sum(c["value"] for c in children)}
        for course, children in courses.items()
    ]
    rest = 100 - float(explanation.score)
    if rest > 0:
        data.append({"name": "", "value": rest, "empty": True})
    return data


@login_required
def po_detail(request, student_id, po_code):
    """How one PO score was computed: what each grade contributed (#41)."""
    student, own_profile, enrollments = _profile_scope(request, student_id)
    from_report = _from_report(request, student)
    explanation = explain_po(student, po_code, enrollments)
    if explanation is None:
        raise Http404

    grades = explanation.by_assessment()
    multi_course = len({p.course for p in grades}) > 1
    lo_by_key = {lo.key: lo for lo in explanation.los}
    links = []
    for lo in explanation.los:
        for leaf, weight in lo.inputs:
            links.append({"from": _grade_name(leaf, grades, multi_course), "to": _lo_name(lo, multi_course),
                          "weight": float(lo.share * weight)})
        links.append({"from": _lo_name(lo, multi_course), "to": po_code, "weight": float(lo.share)})
    points = (
        [{"column": "Grades", "name": _grade_name(p.key, grades, multi_course), "score": float(p.score)}
         for p in grades]
        + [{"column": "Learning outcomes", "name": _lo_name(lo, multi_course), "score": float(lo.score)}
           for lo in lo_by_key.values()]
        + [{"column": po_code, "name": po_code, "score": float(explanation.score)}]
    )

    return render(request, "grading/po_detail.html", {
        "student": student,
        "own_profile": own_profile,
        "po_code": po_code,
        "score": display(explanation.score),
        "thin": len(grades) < MIN_ASSESSMENTS_FOR_SCORE,
        "grades": [
            {"part": p, "name": _grade_name(p.key, grades, multi_course), "percent": display(p.score),
             "weight": display(p.share * 100), "contribution": display(p.contribution)}
            for p in grades
        ],
        "los": [
            {"part": lo, "name": _lo_name(lo, multi_course), "score": display(lo.score),
             "weight": display(lo.share * 100)}
            for lo in explanation.los
        ],
        "chart": {"points": points, "links": links, "po": po_code},
        "from_report": from_report,
        "nav": "home" if own_profile else None,
    })


def _grade_name(leaf, grades, multi_course):
    part = next(p for p in grades if p.key == leaf)
    return f"{part.course} {part.label}" if multi_course else part.label


def _lo_name(lo, multi_course):
    return f"{lo.course} {lo.label}" if multi_course else lo.label


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

    is_grid_request = request.content_type == "application/json"

    try:
        with serializable_transaction():
            assessment = _gradable_assessment(request, assessment_id)
            with grade_change_actor(request.user, using=assessment._state.db):
                if is_grid_request:
                    return _save_pasted_grades(request, assessment)
                if request.POST.get("action") == "confirm":
                    return _confirm_preview(request, assessment)
                return _upload(request, assessment)
    except OperationalError as error:
        if not is_serialization_failure(error):
            raise

    if is_grid_request:
        return JsonResponse(
            {"message": "Grades changed while you were saving. Reload the page and try again."},
            status=409,
        )
    assessment = _gradable_assessment(request, assessment_id)
    if request.POST.get("action") == "import" and _already_saved(request, assessment):
        # Usually a double click: the first request saved this very file (#103).
        return _import_page(request, assessment, already_saved=True)
    return _import_page(
        request,
        assessment,
        errors=["Someone changed these grades at the same time, so nothing was saved. Choose the files again."],
        status=409,
    )


def _already_saved(request, assessment):
    """Do the stored grades already hold exactly what the uploaded files say?"""
    files = request.FILES.getlist("csv_file")
    for uploaded in files:
        uploaded.seek(0)
    enrollments = {e.student.username: e for e in assessment.offering.enrollments.select_related("student")}
    parsed = parse_grade_files(files, assessment, enrollments)
    if parsed.errors or not parsed.rows:
        return False
    stored = {g.enrollment_id: (g.status, g.score) for g in assessment.grades.all()}
    return all(stored.get(e.pk) == (Grade.Status.GRADED, score) for e, score in parsed.rows)


def _gradable_assessment(request, assessment_id):
    return get_object_or_404(
        Assessment.objects.select_related("offering__course", "offering__term"),
        pk=assessment_id,
        offering__in=grade_entry_offerings(request.user),
    )


def _import_page(request, assessment, status=200, **context):
    enrollments = assessment.offering.enrollments.select_related("student").order_by("student__username")
    current = {
        grade.enrollment_id: "absent" if grade.status == Grade.Status.ABSENT else f"{grade.score.normalize():f}"
        for grade in assessment.grades.all()
    }
    paste_rows = [
        {"id": index, "student_number": e.student.username, "score": ""}
        for index, e in enumerate(enrollments)
    ]
    # Name and current grade follow the student number, so after a
    # two column paste the instructor still sees whose row it is.
    paste_students = {
        e.student.username: {"name": e.student.get_full_name(), "current": current.get(e.pk, "")}
        for e in enrollments
    }

    return render(
        request,
        "grading/grade_import.html",
        {
            "assessment": assessment,
            "nav": "home",
            "paste_rows": paste_rows,
            "paste_students": paste_students,
            **context,
        },
        status=status,
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

def _save_pasted_grades(request, assessment):
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"message": "Invalid grade grid data."}, status=400)

    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or any(
        not isinstance(row, dict)
        or not isinstance(row.get("student_number"), str)
        or not isinstance(row.get("score"), str)
        for row in rows
    ):
        return JsonResponse({"message": "Invalid grade grid data."}, status=400)

    enrollments = {
        enrollment.student.username: enrollment
        for enrollment in assessment.offering.enrollments.select_related("student")
    }
    scores, errors = validate_pasted_grades(rows, assessment, enrollments)

    if errors:
        return JsonResponse({"errors": errors}, status=400)
    if not scores:
        return JsonResponse({"message": "Enter at least one score."}, status=400)

    _save_scores(assessment, scores)
    return JsonResponse({"saved_count": len(scores)})

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


@require_POST
def demo_switch(request, role):
    """Sign in as the demo student, instructor or head (#46).

    Only with DEMO=1; otherwise the URL does not exist. POST with CSRF, so a
    link on another site cannot switch someone's session.
    """
    if not settings.DEMO:
        raise Http404
    user = demo_user(role)
    if user is None:
        raise Http404
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return redirect("home")
