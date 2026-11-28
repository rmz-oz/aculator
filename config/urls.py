"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
import os

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.db import connection
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from grading import api as grading_api
from grading import views as grading_views


def healthz(request):
    """Used by Render's health check and the Deploy workflow. Fails if the database is unreachable.

    `version` is the commit the image was built from, so a deploy can wait for the right one.
    """
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
    return JsonResponse({'status': 'ok', 'version': os.environ.get('GIT_SHA', 'dev')})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", healthz),
    path("i18n/", include("django.conf.urls.i18n")),
    path("", grading_views.home, name="home"),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("demo/<slug:role>/", grading_views.demo_switch, name="demo_switch"),
    path(
        "offerings/<int:offering_id>/report/",
        grading_views.course_report,
        name="course_report",
    ),
    path(
        "offerings/<int:offering_id>/outcomes/",
        grading_views.syllabus_import,
        name="syllabus_import",
    ),
    path(
        "offerings/<int:offering_id>/weights/",
        grading_views.assessment_weights,
        name="assessment_weights",
    ),
    path(
        "assessments/<int:assessment_id>/makeup/",
        grading_views.add_makeup,
        name="add_makeup",
    ),
    path(
        "assessments/<int:assessment_id>/import/",
        grading_views.grade_import,
        name="grade_import",
    ),
    path(
        "students/<int:student_id>/profile/",
        grading_views.student_profile,
        name="student_profile",
    ),
    path(
        "students/<int:student_id>/outcomes/<str:po_code>/",
        grading_views.po_detail,
        name="po_detail",
    ),

    path("api/v1/courses/", grading_api.CourseList.as_view(), name="api-courses"),
    path("api/v1/offerings/", grading_api.OfferingList.as_view(), name="api-offerings"),
    path(
        "api/v1/learning-outcomes/",
        grading_api.LearningOutcomeList.as_view(),
        name="api-learning-outcomes",
    ),
    path(
        "api/v1/program-outcomes/",
        grading_api.ProgramOutcomeList.as_view(),
        name="api-program-outcomes",
    ),
    path("api/v1/scores/", grading_api.GradeList.as_view(), name="api-scores"),
    path(
        "api/v1/outcome-scores/",
        grading_api.OutcomeScoreList.as_view(),
        name="api-outcome-scores",
    ),
    path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="api-schema"),
        name="api-docs",
    ),

]
