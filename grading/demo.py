"""Demo accounts for the role switcher (#46).

Three users from the fake data, one per role. They have no usable password, so
the only way in is the switcher, and the switcher exists only with DEMO=1.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from .access import HEAD, INSTRUCTOR, STUDENT
from .models import CourseOffering, Enrollment

# The first fake student; fake_data gives them six courses.
DEMO_STUDENT = "fake_student_0001"
DEMO_INSTRUCTOR = "demo_instructor"
DEMO_HEAD = "demo_head"

# The demo instructor teaches these courses in every term.
DEMO_COURSES = ("CSE203", "CSE301")

# URL slug, label, username. The order is the order on the page.
DEMO_ROLES = (
    ("student", STUDENT, DEMO_STUDENT),
    ("instructor", INSTRUCTOR, DEMO_INSTRUCTOR),
    ("head", HEAD, DEMO_HEAD),
)


def demo_user(slug):
    """The demo account for a role slug, or None."""
    for role_slug, _label, username in DEMO_ROLES:
        if role_slug == slug:
            return get_user_model().objects.filter(username=username, is_active=True).first()
    return None


def ensure_demo_accounts():
    """Create or repair the three accounts. Safe to run on every start.

    Needs the fake data: the student is a fake student and the instructor
    teaches existing offerings. Returns the usernames it could set up.
    """
    User = get_user_model()
    groups = {name: Group.objects.get_or_create(name=name)[0] for name in (STUDENT, INSTRUCTOR, HEAD)}
    ready = []

    student = User.objects.filter(username=DEMO_STUDENT).first()
    if student is not None and Enrollment.objects.filter(student=student).exists():
        student.groups.add(groups[STUDENT])
        ready.append(DEMO_STUDENT)

    for username, first, last, group in (
        (DEMO_INSTRUCTOR, "Deniz", "Demo", INSTRUCTOR),
        (DEMO_HEAD, "Selin", "Demo", HEAD),
    ):
        user, created = User.objects.get_or_create(
            username=username, defaults={"first_name": first, "last_name": last},
        )
        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])
        user.groups.add(groups[group])
        ready.append(username)

    instructor = User.objects.get(username=DEMO_INSTRUCTOR)
    for offering in CourseOffering.objects.filter(course__code__in=DEMO_COURSES):
        offering.instructors.add(instructor)

    return ready
