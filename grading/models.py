from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Term(models.Model):
    """An academic term, e.g. 2026 Fall."""

    class Season(models.TextChoices):
        FALL = "fall", "Güz"
        SPRING = "spring", "Bahar"
        SUMMER = "summer", "Yaz"

    year = models.PositiveSmallIntegerField()
    season = models.CharField(max_length=10, choices=Season.choices)

    class Meta:
        ordering = ("-year", "season")
        constraints = (
            models.UniqueConstraint(fields=["year", "season"], name="uniq_term"),
        )

    def __str__(self):
        return f"{self.year} {self.get_season_display()}"


class ProgramOutcome(models.Model):
    """A program-level outcome (PO) of the department, shared by all courses."""

    code = models.CharField(max_length=10, unique=True)  # e.g. "PO1"
    description = models.TextField(blank=True)

    class Meta:
        ordering = ("code",)

    def __str__(self):
        return self.code


class Course(models.Model):
    """A course in the catalog. Term-independent; see CourseOffering."""

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    credits = models.PositiveSmallIntegerField(default=3)

    class Meta:
        ordering = ("code",)

    def __str__(self):
        return f"{self.code} - {self.name}"


class CourseOffering(models.Model):
    """A course taught in a specific term (course + term).

    Learning outcomes, assessments and enrollments hang off the offering,
    not the course, so a course can change them between terms.
    PROTECT on both FKs: deleting a course or term must not silently wipe
    its grading data.
    """

    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="offerings")
    term = models.ForeignKey(Term, on_delete=models.PROTECT, related_name="offerings")

    class Meta:
        ordering = ("-term__year", "term__season", "course__code")
        constraints = (
            models.UniqueConstraint(fields=["course", "term"], name="uniq_offering_course_term"),
        )

    def __str__(self):
        return f"{self.course.code} ({self.term})"


class LearningOutcome(models.Model):
    """A learning outcome (LO) of one offering.

    Belongs to the offering rather than the course, so the same course can
    have different LOs in different terms.
    """

    offering = models.ForeignKey(
        CourseOffering, on_delete=models.CASCADE, related_name="learning_outcomes"
    )
    code = models.CharField(max_length=10)  # e.g. "LO1", unique within the offering
    description = models.TextField(blank=True)

    class Meta:
        ordering = ("offering", "code")
        constraints = (
            models.UniqueConstraint(fields=["offering", "code"], name="uniq_lo_code_per_offering"),
        )

    def __str__(self):
        return f"{self.offering} / {self.code}"


class Assessment(models.Model):
    """A graded item of an offering (midterm, quiz, project, ...)."""

    offering = models.ForeignKey(
        CourseOffering, on_delete=models.CASCADE, related_name="assessments"
    )
    name = models.CharField(max_length=100)  # e.g. "Midterm"
    # Upper bound for Grade.score, checked in Grade.clean().
    max_score = models.DecimalField(
        max_digits=6, decimal_places=2, default=100,
        validators=[MinValueValidator(0)],
    )

    class Meta:
        ordering = ("offering", "name")
        constraints = (
            models.UniqueConstraint(fields=["offering", "name"], name="uniq_assessment_name_per_offering"),
        )

    def __str__(self):
        return f"{self.offering} / {self.name}"


class Enrollment(models.Model):
    """A student enrolled in an offering.

    The student is the project's user model for now; switch the FK if a
    dedicated Student model is introduced. PROTECT keeps a user with
    enrollments from being deleted by accident.
    """

    offering = models.ForeignKey(
        CourseOffering, on_delete=models.CASCADE, related_name="enrollments"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="enrollments"
    )

    class Meta:
        constraints = (
            models.UniqueConstraint(fields=["offering", "student"], name="uniq_enrollment"),
        )

    def __str__(self):
        return f"{self.student} -> {self.offering}"


class Grade(models.Model):
    """A student's score on one assessment (one grade per enrollment/assessment)."""

    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, related_name="grades")
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name="grades")
    score = models.DecimalField(
        max_digits=6, decimal_places=2, validators=[MinValueValidator(0)]
    )

    class Meta:
        constraints = (
            models.UniqueConstraint(fields=["enrollment", "assessment"], name="uniq_grade"),
        )

    def __str__(self):
        return f"{self.enrollment} / {self.assessment.name}: {self.score}"

    def clean(self):
        """Cross-field checks. Runs in admin and on full_clean(), not on save()."""
        super().clean()
        # Related objects may be missing when the form already failed on them.
        if not (self.enrollment_id and self.assessment_id):
            return
        if self.enrollment.offering_id != self.assessment.offering_id:
            raise ValidationError("Enrollment ve assessment aynı offering'e ait olmalı.")
        if self.score is not None and self.score > self.assessment.max_score:
            raise ValidationError({"score": f"Not, en fazla {self.assessment.max_score} olabilir."})


class AssessmentLOWeight(models.Model):
    """How much an assessment contributes to a learning outcome (weight in [0, 1]).

    Whether the weights of one LO sum to 1 is not enforced here; that belongs
    to the calculation layer.
    """

    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name="lo_weights")
    learning_outcome = models.ForeignKey(
        LearningOutcome, on_delete=models.CASCADE, related_name="assessment_weights"
    )
    weight = models.DecimalField(
        max_digits=5, decimal_places=4,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )

    class Meta:
        constraints = (
            models.UniqueConstraint(fields=["assessment", "learning_outcome"], name="uniq_assessment_lo"),
        )

    def __str__(self):
        return f"{self.assessment.name} -> {self.learning_outcome.code}: {self.weight}"

    def clean(self):
        """The assessment and the LO must belong to the same offering."""
        super().clean()
        if not (self.assessment_id and self.learning_outcome_id):
            return
        if self.assessment.offering_id != self.learning_outcome.offering_id:
            raise ValidationError("Assessment ve LO aynı offering'e ait olmalı.")


class LOPOWeight(models.Model):
    """How much a learning outcome contributes to a program outcome (weight in [0, 1])."""

    learning_outcome = models.ForeignKey(
        LearningOutcome, on_delete=models.CASCADE, related_name="po_weights"
    )
    program_outcome = models.ForeignKey(
        ProgramOutcome, on_delete=models.CASCADE, related_name="lo_weights"
    )
    weight = models.DecimalField(
        max_digits=5, decimal_places=4,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )

    class Meta:
        constraints = (
            models.UniqueConstraint(fields=["learning_outcome", "program_outcome"], name="uniq_lo_po"),
        )

    def __str__(self):
        return f"{self.learning_outcome.code} -> {self.program_outcome.code}: {self.weight}"