import csv
from decimal import Decimal, InvalidOperation
from io import StringIO

from django.core import signing
from django.db import OperationalError, connection, transaction
from django.shortcuts import get_object_or_404, render

from .access import report_offerings
from .models import Assessment, Grade
from .services import display, scores_by_enrollment, weighted_mean

ONE = Decimal(1)


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
def grade_import(request, assessment_id):
    if request.method != "POST":
        return _grade_import(request, assessment_id)

    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            return _grade_import(request, assessment_id)
    except OperationalError as error:
        if getattr(error.__cause__, "sqlstate", None) != "40001":
            raise

        return render(
            request,
            "grading/grade_import.html",
            {
                "errors": [
                    "Eşzamanlı bir işlem nedeniyle bu yükleme kaydedilemedi. "
                    "CSV dosyalarını yeniden seçip tekrar dene."
                ],
            },
            status=409,
        )

def _grade_import(request, assessment_id):
    assessment = get_object_or_404(
        Assessment,
        pk=assessment_id,
        offering__in=report_offerings(request.user),
    )
    errors = []
    valid_rows = []
    saved_count = 0
    missing_students = None
    preview_token = None

    if request.method == "POST" and request.POST.get("action") == "confirm":
        try:
            preview = signing.loads(
                request.POST.get("preview_token", ""),
                salt="grade-import-preview",
                max_age=900,
            )
        except signing.BadSignature:
            preview = None

        if (
            preview is None
            or preview["assessment_id"] != assessment.pk
            or preview["user_id"] != request.user.pk
        ):
            errors.append("Önizleme geçersiz veya süresi dolmuş. Dosyaları yeniden önizle.")
        else:
            selected = set(request.POST.getlist("absent_students"))
            missing = preview["missing"]
            scores = [
                (enrollment_id, Decimal(score))
                for enrollment_id, score in preview["scores"]
            ]
            current_ids = set(
                assessment.offering.enrollments.values_list("pk", flat=True)
            )
            preview_ids = {enrollment_id for enrollment_id, _ in scores} | set(
                missing.values()
            )

            if not selected.issubset(missing):
                errors.append("Yalnızca önizlemede önerilen öğrenciler seçilebilir.")
            elif current_ids != preview_ids:
                errors.append("Ders kayıtları değişti. Dosyaları yeniden önizle.")
            elif any(score > assessment.max_score for _, score in scores):
                errors.append("Sınavın maksimum puanı değişti. Dosyaları yeniden önizle.")
            else:
                for enrollment_id, score in scores:
                    Grade.objects.update_or_create(
                        assessment=assessment,
                        enrollment_id=enrollment_id,
                        defaults={"score": score, "status": Grade.Status.GRADED},
                    )

                absent_count = 0
                for number in sorted(selected):
                    _, created = Grade.objects.get_or_create(
                        assessment=assessment,
                        enrollment_id=missing[number],
                        defaults={"score": 0, "status": Grade.Status.ABSENT},
                    )
                    absent_count += int(created)

                return render(request, "grading/grade_import.html", {
                    "assessment": assessment,
                    "saved_count": len(scores),
                    "absent_count": absent_count,
                })

        return render(request, "grading/grade_import.html", {
            "assessment": assessment,
            "errors": errors,
        })

    if request.method == "POST":
        uploaded_files = request.FILES.getlist("csv_file")

        if not uploaded_files:
            errors.append("En az bir CSV dosyası seç.")
        else:
            enrollments = {
                enrollment.student.username: enrollment
                for enrollment in assessment.offering.enrollments.select_related("student")
            }
            seen_numbers = {}

            for uploaded_file in uploaded_files:
                try:
                    content = uploaded_file.read().decode("utf-8-sig")
                    reader = csv.DictReader(StringIO(content), strict=True)

                    if reader.fieldnames != ["student_number", "score"]:
                        errors.append(
                            f"{uploaded_file.name}: İlk satır student_number,score olmalı."
                        )
                        continue

                    has_rows = False
                    for row in reader:
                        has_rows = True
                        location = f"{uploaded_file.name}, {reader.line_num}. satır"
                        number = (row.get("student_number") or "").strip()
                        enrollment = enrollments.get(number)

                        if None in row:
                            errors.append(f"{location}: Fazladan sütun var.")

                        if not number:
                            errors.append(f"{location}: Öğrenci numarası boş.")
                        else:
                            if enrollment is None:
                                errors.append(f"{location}: {number} bu derse kayıtlı değil.")
                            if number in seen_numbers:
                                errors.append(
                                    f"{location}: {number} tekrar ediyor. "
                                    f"İlk kayıt: {seen_numbers[number]}."
                                )
                            else:
                                seen_numbers[number] = location

                        try:
                            score = Decimal(row.get("score") or "")
                        except InvalidOperation:
                            errors.append(f"{location}: Puan sayı olmalı.")
                            continue

                        if not score.is_finite() or not 0 <= score <= assessment.max_score:
                            errors.append(
                                f"{location}: Puan 0 ile {assessment.max_score} arasında olmalı."
                            )
                        elif score.as_tuple().exponent < -2:
                            errors.append(f"{location}: Puan en fazla iki ondalık basamak içerebilir.")
                        elif enrollment is not None:
                            valid_rows.append((enrollment, score))

                    if not has_rows:
                        errors.append(f"{uploaded_file.name}: Dosyada not satırı yok.")
                except (UnicodeDecodeError, csv.Error):
                    errors.append(f"{uploaded_file.name}: Dosya okunamadı.")


        if not errors and request.POST.get("action") == "preview":
            missing_students = sorted(enrollments.keys() - seen_numbers.keys())
            preview_token = signing.dumps({
                "assessment_id": assessment.pk,
                "user_id": request.user.pk,
                "scores": [
                    [enrollment.pk, str(score)]
                    for enrollment, score in valid_rows
                ],
                "missing": {
                    number: enrollments[number].pk
                    for number in missing_students
                },
            }, salt="grade-import-preview")
        elif not errors:
            for enrollment, score in valid_rows:
                Grade.objects.update_or_create(
                    assessment=assessment,
                    enrollment=enrollment,
                    defaults={
                        "score": score,
                        "status": Grade.Status.GRADED,
                    },
                )
            saved_count = len(valid_rows)

    return render(request, "grading/grade_import.html", {
        "assessment": assessment,
        "errors": errors,
        "saved_count": saved_count,
        "missing_students": missing_students,
        "preview_token": preview_token,
    })
