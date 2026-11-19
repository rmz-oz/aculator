"""Who can see what.

Three roles, kept as Django groups:

- Student: only their own enrollments and grades.
- Instructor: the offerings they teach (CourseOffering.instructors), with all
  enrollments and grades in them.
- Head of department: everything. There is one department for now (see
  docs/decisions/0007-roles.md).

A superuser counts as head. A user in more than one group gets the widest role.
Views and querysets should go through these functions instead of filtering
by hand, so the rules live in one place.
"""

from .models import CourseOffering, Enrollment, Grade

STUDENT = "Student"
INSTRUCTOR = "Instructor"
HEAD = "Head of department"

ROLES = (STUDENT, INSTRUCTOR, HEAD)


def role_of(user):
    """The widest role the user has, or None."""
    if not user.is_authenticated or not user.is_active:
        return None
    if user.is_superuser:
        return HEAD
    # One group query per request: the views, access checks and the masthead
    # all ask. Group changes show up on the next request.
    if not hasattr(user, "_aculator_role"):
        names = set(user.groups.values_list("name", flat=True))
        user._aculator_role = next((r for r in (HEAD, INSTRUCTOR, STUDENT) if r in names), None)
    return user._aculator_role


def visible_offerings(user):
    role = role_of(user)
    qs = CourseOffering.objects.all()
    if role == HEAD:
        return qs
    if role == INSTRUCTOR:
        return qs.filter(instructors=user)
    if role == STUDENT:
        return qs.filter(enrollments__student=user).distinct()
    return qs.none()


def report_offerings(user):
    """Offerings whose class report the user may open.

    A class report lists every student's scores, so students get none, even in
    courses they take: the head sees every offering, an instructor the ones they teach.
    """
    role = role_of(user)
    if role == HEAD:
        return CourseOffering.objects.all()
    if role == INSTRUCTOR:
        return CourseOffering.objects.filter(instructors=user)
    return CourseOffering.objects.none()


def grade_entry_offerings(user):
    """Offerings whose grades the user may write, e.g. by CSV import.

    Only the people who teach the offering (CourseOffering.instructors). The
    head reads every report but enters no grades, and neither does a superuser
    unless they are listed as an instructor of that offering.
    """
    if role_of(user) not in (INSTRUCTOR, HEAD):
        return CourseOffering.objects.none()
    return CourseOffering.objects.filter(instructors=user)


def visible_enrollments(user):
    role = role_of(user)
    qs = Enrollment.objects.all()
    if role == HEAD:
        return qs
    if role == INSTRUCTOR:
        return qs.filter(offering__instructors=user)
    if role == STUDENT:
        return qs.filter(student=user)
    return qs.none()


def visible_grades(user):
    role = role_of(user)
    qs = Grade.objects.all()
    if role == HEAD:
        return qs
    if role == INSTRUCTOR:
        return qs.filter(enrollment__offering__instructors=user)
    if role == STUDENT:
        return qs.filter(enrollment__student=user)
    return qs.none()


def can_view_student(viewer, student):
    """Can `viewer` open `student`'s profile (PO scores across courses)?

    An instructor who teaches the student in one course may see the profile,
    but visible_grades() still limits the numbers to their own offerings.
    """
    role = role_of(viewer)
    if role is None:
        return False
    if role == HEAD:
        return True
    if viewer.pk == student.pk:
        return True
    if role == INSTRUCTOR:
        return Enrollment.objects.filter(student=student, offering__instructors=viewer).exists()
    return False
