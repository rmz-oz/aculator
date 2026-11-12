from decimal import Decimal

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


class POComponent(models.Model):
    """A separately evidenced component of a program outcome (MÜDEK 3.3, #25)."""

    program_outcome = models.ForeignKey(
        ProgramOutcome,
        on_delete=models.CASCADE,
        related_name="components",
    )
    code = models.CharField(max_length=10)  # e.g. "a", unique within the PO
    description = models.TextField(blank=True)

    class Meta:
        ordering = ("program_outcome__code", "code")
        constraints = (
            models.UniqueConstraint(fields=["program_outcome", "code"], name="uniq_po_component"),
        )

    def __str__(self):
        return f"{self.program_outcome.code}.{self.code}"


class Course(models.Model):
    """A course in the catalog. Term-independent; see CourseOffering."""

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    ects = models.PositiveSmallIntegerField()

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
    # Who teaches this offering. Instructors see only the offerings listed here.
    instructors = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="teaching"
    )

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
    # Upper bound for Grade.score, checked in Grade.clean(). Must be positive,
    # the calculation divides by it.
    max_score = models.DecimalField(
        max_digits=6, decimal_places=2, default=100,
        validators=[MinValueValidator(Decimal("0.01"))],
    )

    class Meta:
        ordering = ("offering", "name")
        constraints = (
            models.UniqueConstraint(
                fields=["offering", "name"],
                name="uniq_assessment_name_per_offering",
            ),
            models.CheckConstraint(
                condition=models.Q(max_score__gt=0),
                name="assessment_max_score_positive",
            ),
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
    """A student's score on one assessment (one grade per enrollment/assessment).

    No row means the grade is not entered yet and the assessment is left out
    of the calculation. An absent student has a row with status ABSENT and
    score 0, which counts as 0 (#72).
    """

    class Status(models.TextChoices):
        GRADED = "graded", "Graded"
        ABSENT = "absent", "Absent"

    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, related_name="grades")
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name="grades")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.GRADED)
    # blank=True so a form can leave it empty for an absent student; clean()
    # fills in 0 or asks for a score. The column stays NOT NULL.
    score = models.DecimalField(
        max_digits=6, decimal_places=2, blank=True, validators=[MinValueValidator(0)]
    )

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=["enrollment", "assessment"],
                name="uniq_grade",
            ),
            models.CheckConstraint(
                condition=models.Q(score__gte=0),
                name="grade_score_nonnegative",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="absent") | models.Q(score=0),
                name="grade_absent_is_zero",
            ),
        )

    def __str__(self):
        shown = "absent" if self.status == self.Status.ABSENT else self.score
        return f"{self.enrollment} / {self.assessment.name}: {shown}"

    def clean(self):
        """Cross-field checks. Runs in admin and on full_clean(), not on save()."""
        if self.status == self.Status.ABSENT:
            if self.score is None:
                self.score = Decimal(0)
            elif self.score != 0:
                raise ValidationError({"score": "An absent student's score must be 0."})
        elif self.score is None:
            raise ValidationError({"score": "Enter a score or mark the student absent."})
        super().clean()
        if not (self.enrollment_id and self.assessment_id):
            return

        if self.enrollment.offering_id != self.assessment.offering_id:
            raise ValidationError(
                "Enrollment and assessment must belong to the same offering."
            )

        if self.score is not None and self.score > self.assessment.max_score:
            raise ValidationError({
                "score": f"Score must not exceed {self.assessment.max_score}."
            })


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
            models.UniqueConstraint(
                fields=["assessment", "learning_outcome"],
                name="uniq_assessment_lo",
            ),
            models.CheckConstraint(
                condition=models.Q(weight__gte=0, weight__lte=1),
                name="assessment_lo_weight_range",
            ),
        )

    def __str__(self):
        return f"{self.assessment.name} -> {self.learning_outcome.code}: {self.weight}"

    def clean(self):
        """The assessment and the LO must belong to the same offering."""
        super().clean()
        if not (self.assessment_id and self.learning_outcome_id):
            return
        if self.assessment.offering_id != self.learning_outcome.offering_id:
            raise ValidationError(
                "Assessment and learning outcome must belong to the same offering."
            )



class LOPOWeight(models.Model):
    """An LO's contribution level to a PO component, on an integer scale from 1 to 5."""

    learning_outcome = models.ForeignKey(
        LearningOutcome,
        on_delete=models.CASCADE,
        related_name="po_weights",
    )
    component = models.ForeignKey(
        POComponent,
        on_delete=models.CASCADE,
        related_name="lo_weights",
    )
    weight = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=["learning_outcome", "component"],
                name="uniq_lo_component",
            ),
            models.CheckConstraint(
                condition=models.Q(weight__gte=1, weight__lte=5),
                name="lo_po_weight_range",
            ),
        )

    def __str__(self):
        return (
            f"{self.learning_outcome.code} -> "
            f"{self.component}: {self.weight}"
        )
