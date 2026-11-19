from .access import role_of


def role(request):
    """The signed-in user's role for the masthead (grading.access.role_of)."""
    return {"role": role_of(request.user) if hasattr(request, "user") else None}
