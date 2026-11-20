from django.conf import settings

from .access import role_of
from .demo import DEMO_ROLES


def role(request):
    """The signed-in user's role for the masthead (grading.access.role_of), and
    the demo roles when the role switcher is on (#46)."""
    return {
        "role": role_of(request.user) if hasattr(request, "user") else None,
        "demo_roles": [(slug, label) for slug, label, _ in DEMO_ROLES] if settings.DEMO else [],
    }
