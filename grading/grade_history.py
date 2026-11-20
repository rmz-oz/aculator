
from contextlib import contextmanager

from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.urls import Resolver404, resolve


@contextmanager
def grade_change_actor(user, using=DEFAULT_DB_ALIAS):
    with transaction.atomic(using=using):
        with connections[using].cursor() as cursor:
            cursor.execute("SELECT current_setting('aculator.grade_changed_by', true)")
            previous_actor = cursor.fetchone()[0]
            cursor.execute(
                "SELECT set_config('aculator.grade_changed_by', %s, true)",
                [user.get_username()],
            )

        yield

        with connections[using].cursor() as cursor:
            cursor.execute(
                "SELECT set_config('aculator.grade_changed_by', %s, true)",
                [previous_actor or ""],
            )

class AdminGradeHistoryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method != "POST" or not request.user.is_authenticated:
            return self.get_response(request)

        try:
            match = resolve(request.path_info)
        except Resolver404:
            return self.get_response(request)

        if "admin" in match.app_names:
            with grade_change_actor(request.user):
                return self.get_response(request)

        return self.get_response(request)