from django.contrib import admin

from . import models as m


class LearningOutcomeInline(admin.TabularInline):
    model = m.LearningOutcome
    extra = 0


class AssessmentInline(admin.TabularInline):
    model = m.Assessment
    extra = 0


class EnrollmentInline(admin.TabularInline):
    model = m.Enrollment
    extra = 0
    autocomplete_fields = ["student"]


class AssessmentLOWeightInline(admin.TabularInline):
    model = m.AssessmentLOWeight
    extra = 0


class LOPOWeightInline(admin.TabularInline):
    model = m.LOPOWeight
    extra = 0


@admin.register(m.Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ("year", "season")
    list_filter = ("season",)


@admin.register(m.ProgramOutcome)
class ProgramOutcomeAdmin(admin.ModelAdmin):
    list_display = ("code", "description")
    search_fields = ("code", "description")


@admin.register(m.Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "credits")
    search_fields = ("code", "name")


@admin.register(m.CourseOffering)
class CourseOfferingAdmin(admin.ModelAdmin):
    list_display = ("course", "term")
    list_filter = ("term",)
    list_select_related = ("course", "term")
    search_fields = ("course__code", "course__name")
    autocomplete_fields = ["course"]
    inlines = [LearningOutcomeInline, AssessmentInline, EnrollmentInline]


@admin.register(m.LearningOutcome)
class LearningOutcomeAdmin(admin.ModelAdmin):
    list_display = ("code", "offering", "description")
    list_filter = ("offering__term",)
    list_select_related = ("offering__course", "offering__term")
    search_fields = ("code", "offering__course__code")
    autocomplete_fields = ["offering"]
    inlines = [LOPOWeightInline]


@admin.register(m.Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = ("name", "offering", "max_score")
    list_filter = ("offering__term",)
    list_select_related = ("offering__course", "offering__term")
    search_fields = ("name", "offering__course__code")
    autocomplete_fields = ["offering"]
    inlines = [AssessmentLOWeightInline]


@admin.register(m.Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("student", "offering")
    list_filter = ("offering__term",)
    list_select_related = ("student", "offering__course", "offering__term")
    search_fields = ("student__username", "offering__course__code")
    autocomplete_fields = ["offering", "student"]


@admin.register(m.Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ("enrollment", "assessment", "score")
    list_filter = ("assessment__offering__term",)
    list_select_related = (
        "enrollment__student",
        "enrollment__offering__course",
        "assessment__offering__course",
    )
    autocomplete_fields = ["enrollment", "assessment"]


@admin.register(m.AssessmentLOWeight)
class AssessmentLOWeightAdmin(admin.ModelAdmin):
    list_display = ("assessment", "learning_outcome", "weight")
    list_select_related = ("assessment", "learning_outcome")


@admin.register(m.LOPOWeight)
class LOPOWeightAdmin(admin.ModelAdmin):
    list_display = ("learning_outcome", "program_outcome", "weight")
    list_select_related = ("learning_outcome", "program_outcome")


from django.contrib import admin

# Register your models here.
