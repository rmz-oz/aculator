from django.db.models import BooleanField, Exists, ExpressionWrapper, OuterRef, Q
from rest_framework import serializers
from rest_framework.generics import ListAPIView

from .access import visible_enrollments, visible_grades, visible_offerings
from .models import Course, CourseOffering, Grade, LearningOutcome, ProgramOutcome
from .services import counting_enrollment_ids, scores_by_enrollment


class CourseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = ("id", "code", "name", "ects")


class OfferingSerializer(serializers.ModelSerializer):
    term_year = serializers.IntegerField(source="term.year", read_only=True)
    term_season = serializers.CharField(source="term.season", read_only=True)

    class Meta:
        model = CourseOffering
        fields = ("id", "course", "term_year", "term_season", "ects")


class LearningOutcomeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LearningOutcome
        fields = ("id", "offering", "code", "description")


class ProgramOutcomeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProgramOutcome
        fields = ("id", "code", "description")


class GradeSerializer(serializers.ModelSerializer):
    offering = serializers.IntegerField(source="enrollment.offering_id", read_only=True)
    student = serializers.IntegerField(source="enrollment.student_id", read_only=True)
    max_score = serializers.DecimalField(
        source="assessment.max_score",
        max_digits=6,
        decimal_places=2,
        read_only=True,
    )

    counts = serializers.BooleanField(
        read_only=True,
        help_text="False when the grade is left out of the calculation: a graded makeup replaced it, "
        "or it is a makeup the student was absent from (decision 0011).",
    )

    class Meta:
        model = Grade
        fields = ("id", "offering", "student", "assessment", "score", "max_score", "status", "counts")


class OutcomeScoreSerializer(serializers.Serializer):
    enrollment = serializers.IntegerField()
    offering = serializers.IntegerField()
    student = serializers.IntegerField()
    counts_across_courses = serializers.BooleanField(
        help_text="False for an earlier attempt of a retaken course: only the latest attempt with grades "
        "counts in the student's cross-course scores (decision 0011).",
    )
    learning_outcomes = serializers.DictField(
        child=serializers.CharField(),
        help_text="Learning outcome IDs mapped to decimal scores as strings.",
    )
    program_outcomes = serializers.DictField(
        child=serializers.CharField(),
        help_text="Program outcome codes mapped to decimal scores as strings.",
    )


class CourseList(ListAPIView):
    serializer_class = CourseSerializer

    def get_queryset(self):
        course_ids = visible_offerings(self.request.user).values("course_id")
        return Course.objects.filter(pk__in=course_ids).order_by("code", "pk")


class OfferingList(ListAPIView):
    serializer_class = OfferingSerializer

    def get_queryset(self):
        return visible_offerings(self.request.user).select_related("term").order_by("pk")


class LearningOutcomeList(ListAPIView):
    serializer_class = LearningOutcomeSerializer

    def get_queryset(self):
        offerings = visible_offerings(self.request.user)
        return LearningOutcome.objects.filter(offering__in=offerings).order_by(
            "offering_id", "code", "pk"
        )


class ProgramOutcomeList(ListAPIView):
    """List the shared program outcome definitions."""

    serializer_class = ProgramOutcomeSerializer
    queryset = ProgramOutcome.objects.order_by("code", "pk")


class GradeList(ListAPIView):
    """List assessment scores visible to the authenticated user."""

    serializer_class = GradeSerializer

    def get_queryset(self):
        replaced = Grade.objects.filter(
            enrollment_id=OuterRef("enrollment_id"),
            assessment__replaces_id=OuterRef("assessment_id"),
            status=Grade.Status.GRADED,
        )
        absent_makeup = Q(assessment__replaces__isnull=False, status=Grade.Status.ABSENT)
        return (
            visible_grades(self.request.user)
            .select_related("enrollment", "assessment")
            .annotate(counts=ExpressionWrapper(~Q(Exists(replaced)) & ~absent_makeup, output_field=BooleanField()))
            .order_by("term_id", "pk")
        )


class OutcomeScoreList(ListAPIView):
    """List calculated LO and PO scores per visible enrollment."""

    serializer_class = OutcomeScoreSerializer

    def get_queryset(self):
        return visible_enrollments(self.request.user).order_by("pk")

    def list(self, request, *args, **kwargs):
        enrollments = self.paginate_queryset(self.get_queryset())
        scores = scores_by_enrollment(enrollments)
        counting = set()
        for student_id in {enrollment.student_id for enrollment in enrollments}:
            counting |= counting_enrollment_ids(student_id)
        rows = []

        for enrollment in enrollments:
            lo_scores, po_scores = scores[enrollment.pk]
            rows.append(
                {
                    "enrollment": enrollment.pk,
                    "offering": enrollment.offering_id,
                    "student": enrollment.student_id,
                    "counts_across_courses": enrollment.pk in counting,
                    "learning_outcomes": {
                        str(lo_id): str(score) for lo_id, score in lo_scores.items()
                    },
                    "program_outcomes": {
                        code: str(score) for code, score in po_scores.items()
                    },
                }
            )

        return self.get_paginated_response(self.get_serializer(rows, many=True).data)
