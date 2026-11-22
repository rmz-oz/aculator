import html
import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse

from .access import HEAD, INSTRUCTOR, STUDENT
from .materialized_views import refresh_materialized_views
from .models import (
    Assessment,
    AssessmentLOWeight,
    Course,
    CourseOffering,
    Enrollment,
    Grade,
    LearningOutcome,
    LOPOWeight,
    POComponent,
    ProgramOutcome,
    Term,
)
from .services import scores_with_evidence_by_enrollment

D = Decimal


class CourseReportViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.term = Term.objects.create(year=2026, season=Term.Season.FALL)
        cls.course = Course.objects.create(code="CSE311", name="Software Engineering", ects=6)
        cls.offering = CourseOffering.objects.create(course=cls.course, term=cls.term)
        cls.po1 = ProgramOutcome.objects.create(code="PO1")
        cls.lo1 = LearningOutcome.objects.create(offering=cls.offering, code="LO1")
        component = POComponent.objects.create(program_outcome=cls.po1, code="a")
        LOPOWeight.objects.create(learning_outcome=cls.lo1, component=component, weight=1)

        cls.midterm = Assessment.objects.create(offering=cls.offering, name="Midterm", max_score=D("100"))
        AssessmentLOWeight.objects.create(assessment=cls.midterm, learning_outcome=cls.lo1, weight=D("1"))

        cls.graded = get_user_model().objects.create_user(
            username="elif", first_name="Elif", last_name="Demir",
        )
        cls.graded_enrollment = Enrollment.objects.create(offering=cls.offering, student=cls.graded)
        Grade.objects.create(enrollment=cls.graded_enrollment, assessment=cls.midterm, score=D("90"))

        cls.ungraded = get_user_model().objects.create_user(username="can")
        Enrollment.objects.create(offering=cls.offering, student=cls.ungraded)

        users = get_user_model().objects
        cls.head = users.create_user(username="head")
        cls.head.groups.add(Group.objects.get(name=HEAD))
        cls.teacher = users.create_user(username="teacher")
        cls.teacher.groups.add(Group.objects.get(name=INSTRUCTOR))
        cls.offering.instructors.add(cls.teacher)
        cls.other_teacher = users.create_user(username="other-teacher")
        cls.other_teacher.groups.add(Group.objects.get(name=INSTRUCTOR))
        cls.graded.groups.add(Group.objects.get(name=STUDENT))

    def test_po_counts_one_assessment_reaching_it_through_two_los(self):
        lo2 = LearningOutcome.objects.create(offering=self.offering, code="LO2")
        AssessmentLOWeight.objects.create(
            assessment=self.midterm, learning_outcome=lo2, weight=D(1)
        )
        component = POComponent.objects.get(program_outcome=self.po1, code="a")
        LOPOWeight.objects.create(learning_outcome=lo2, component=component, weight=1)

        _, _, lo_counts, po_counts = scores_with_evidence_by_enrollment(
            [self.graded_enrollment]
        )[self.graded_enrollment.pk]

        self.assertEqual(lo_counts, {self.lo1.pk: 1, lo2.pk: 1})
        self.assertEqual(po_counts, {"PO1": 1})

    def setUp(self):
        self.client.force_login(self.head)
        # The report reads the score views. A TestCase never commits, so the
        # refresh signals.py schedules never runs; each test refreshes itself.
        refresh_materialized_views()

    def test_renders_scores_and_class_average(self):
        final = Assessment.objects.create(offering=self.offering, name="Final", max_score=D(100))
        AssessmentLOWeight.objects.create(
            assessment=final, learning_outcome=self.lo1, weight=D(1)
        )
        Grade.objects.create(
            enrollment=self.graded_enrollment, assessment=final, score=D(80)
        )
        refresh_materialized_views()

        response = self.client.get(reverse("course_report", args=[self.offering.pk]))
        profile = reverse("student_profile", args=[self.graded.pk]) + f"?from={self.offering.pk}"

        self.assertContains(
            response,
            f"""
            <tr>
                <th scope="row"><a href="{profile}">Elif Demir</a></th>
                <td>85.0</td>
                <td class="po">85.0</td>
            </tr>
            """,
            html=True,
        )
        self.assertEqual(response.context["lo_class_avg"], [D("85.0")])
        self.assertEqual(response.context["po_class_avg"], [D("85.0")])

    def test_report_distinguishes_low_evidence_from_no_evidence(self):
        response = self.client.get(reverse("course_report", args=[self.offering.pk]))
        def profile(user):
            return reverse("student_profile", args=[user.pk]) + f"?from={self.offering.pk}"


        self.assertContains(
            response,
            f"""
            <tr>
                <th scope="row"><a href="{profile(self.graded)}">Elif Demir</a></th>
                <td><span class="thin" title="Only 1 graded assessment so far">1 grade</span></td>
                <td class="po"><span class="thin" title="Only 1 graded assessment so far">1 grade</span></td>
            </tr>
            """,
            html=True,
        )
        self.assertContains(
            response,
            f"""
            <tr>
                <th scope="row"><a href="{profile(self.ungraded)}">can</a></th>
                <td><span class="missing" title="No graded evidence"><span class="sr-only">no evidence</span></span></td>
                <td class="po"><span class="missing" title="No graded evidence"><span class="sr-only">no evidence</span></span></td>
            </tr>
            """,
            html=True,
        )

    def test_class_average_leaves_out_thin_evidence(self):
        final = Assessment.objects.create(offering=self.offering, name="Final", max_score=D(100))
        AssessmentLOWeight.objects.create(assessment=final, learning_outcome=self.lo1, weight=D(1))
        Grade.objects.create(enrollment=self.graded_enrollment, assessment=final, score=D(80))
        # Can has one grade only: shown as "1 grade" and left out of the average.
        can_enrollment = Enrollment.objects.get(offering=self.offering, student=self.ungraded)
        Grade.objects.create(enrollment=can_enrollment, assessment=self.midterm, score=D(10))
        refresh_materialized_views()

        response = self.client.get(reverse("course_report", args=[self.offering.pk]))

        self.assertEqual(response.context["lo_class_avg"], [D("85.0")])
        self.assertEqual(response.context["po_class_avg"], [D("85.0")])

    def test_unknown_offering_is_404(self):
        response = self.client.get(reverse("course_report", args=[self.offering.pk + 999]))

        self.assertEqual(response.status_code, 404)

    def test_offering_with_no_enrollments(self):
        empty_offering = CourseOffering.objects.create(
            course=Course.objects.create(code="CSE999", name="Empty", ects=3),
            term=self.term,
        )

        response = self.client.get(reverse("course_report", args=[empty_offering.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No students enrolled yet")

    def test_query_count_does_not_grow_per_student(self):
        for i in range(10):
            student = get_user_model().objects.create_user(username=f"extra{i}")
            Enrollment.objects.create(offering=self.offering, student=student)

        # session, user, role, then offering, LOs, enrollments, the terms to read grades from (#33),
        # LO and PO scores from the views, grades, LO weights, PO weights,
        # and whether the viewer may import grades here
        with self.assertNumQueries(13):
            self.client.get(reverse("course_report", args=[self.offering.pk]))

    def test_student_names_open_their_profile_for_whoever_reads_the_report(self):
        # The profile is open to the head and the course's instructors, so the
        # report links each name to it. Every link must open, ungraded students too.
        co_teacher = get_user_model().objects.create_user(username="co-teacher")
        co_teacher.groups.add(Group.objects.get(name=INSTRUCTOR))
        self.offering.instructors.add(co_teacher)
        expected = {
            reverse("student_profile", args=[u.pk]) + f"?from={self.offering.pk}"
            for u in (self.graded, self.ungraded)
        }
        for user in (self.head, self.teacher, co_teacher):
            with self.subTest(user=user):
                self.client.force_login(user)
                report = self.client.get(reverse("course_report", args=[self.offering.pk]))
                links = set(re.findall(r'<th scope="row"><a href="([^"]+)"', report.content.decode()))
                links = {html.unescape(link) for link in links}
                self.assertEqual(links, expected)
                for url in links:
                    self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_profile_opened_from_the_report_links_back_to_it(self):
        self.client.force_login(self.teacher)
        report_url = reverse("course_report", args=[self.offering.pk])
        profile = self.client.get(reverse("student_profile", args=[self.graded.pk]), {"from": self.offering.pk})
        self.assertContains(profile, f'href="{report_url}"')
        self.assertContains(profile, f"?from={self.offering.pk}")  # carried on to the PO detail links
        detail = self.client.get(reverse("po_detail", args=[self.graded.pk, "PO1"]), {"from": self.offering.pk})
        self.assertContains(detail, f"?from={self.offering.pk}")

    def test_back_link_only_for_a_report_the_viewer_may_open(self):
        # A hand-edited ?from must not name a course the viewer cannot open,
        # nor one the student is not in.
        other = CourseOffering.objects.create(course=Course.objects.create(code="CSE999", name="Other", ects=5),
                                              term=self.term)
        loner = get_user_model().objects.create_user(username="loner")
        Enrollment.objects.create(offering=other, student=loner)
        report_url = reverse("course_report", args=[self.offering.pk])
        Enrollment.objects.create(offering=other, student=self.graded)
        cases = [
            (self.teacher, self.graded, other.pk),  # the student is in it, but the teacher may not open it
            (self.head, loner, self.offering.pk),  # the head may open it, but this student is not in it
            (self.teacher, self.graded, "abc"),
            (self.teacher, self.graded, "²"),  # str.isdigit() is True, int() fails
        ]
        for user, student, from_id in cases:
            with self.subTest(user=user, from_id=from_id):
                self.client.force_login(user)
                profile = self.client.get(reverse("student_profile", args=[student.pk]), {"from": from_id})
                self.assertEqual(profile.status_code, 200)
                self.assertNotContains(profile, "class report</a>")
                self.assertNotContains(profile, f'href="{report_url}"')

    def test_only_head_and_own_instructor_can_open_the_report(self):
        url = reverse("course_report", args=[self.offering.pk])
        cases = [
            (None, 302),  # logged out, sent to the login page (#77)
            (self.graded, 404),  # a student, even one in this course
            (self.other_teacher, 404),
            (self.teacher, 200),
            (self.head, 200),
        ]
        for user, status in cases:
            with self.subTest(user=user):
                self.client.logout()
                if user:
                    self.client.force_login(user)
                self.assertEqual(self.client.get(url).status_code, status)


class HomeViewTests(TestCase):
    """The start page, with the course report fixtures: one offering, a teacher, the head."""

    setUpTestData = classmethod(CourseReportViewTests.setUpTestData.__func__)

    def get_home(self, user):
        self.client.force_login(user)
        return self.client.get(reverse("home"))

    def test_instructor_sees_their_course_with_import_links(self):
        response = self.get_home(self.teacher)

        self.assertContains(response, "CSE311")
        self.assertContains(response, reverse("grade_import", args=[self.midterm.pk]))
        self.assertContains(response, "1 of 2 graded")

    def test_class_report_links_name_the_course_and_term(self):
        # Every card has a "Class report" link; a screen reader's link list needs to tell them apart.
        spring = Term.objects.create(year=2027, season=Term.Season.SPRING)
        CourseOffering.objects.create(course=self.course, term=spring).instructors.add(self.teacher)
        response = self.get_home(self.teacher)
        self.assertContains(response, f'aria-label="Class report, CSE311 {self.term}"')
        self.assertContains(response, f'aria-label="Class report, CSE311 {spring}"')

    def test_newest_term_is_open_and_earlier_terms_fold(self):
        spring = Term.objects.create(year=2027, season=Term.Season.SPRING)
        CourseOffering.objects.create(course=self.course, term=spring).instructors.add(self.teacher)
        content = self.get_home(self.teacher).content.decode()
        open_part, _, folded = content.partition('<details class="term">')
        self.assertIn(f'<h2 class="term">{spring}</h2>', open_part)
        self.assertIn(f'<h2 class="term">{self.term}</h2>', folded)

    def test_head_sees_the_report_but_no_import_link(self):
        response = self.get_home(self.head)

        self.assertContains(response, reverse("course_report", args=[self.offering.pk]))
        self.assertNotContains(response, reverse("grade_import", args=[self.midterm.pk]))

    def test_other_instructor_sees_no_course(self):
        response = self.get_home(self.other_teacher)

        self.assertNotContains(response, "CSE311")
        self.assertContains(response, "You are not listed as an instructor of any course")

    def test_head_with_no_offerings_is_not_told_they_teach_nothing(self):
        CourseOffering.objects.all().delete()

        response = self.get_home(self.head)

        self.assertContains(response, "No course offerings yet")
        self.assertNotContains(response, "instructor of any course")

    def test_student_goes_to_their_profile(self):
        response = self.get_home(self.graded)

        self.assertRedirects(
            response, reverse("student_profile", args=[self.graded.pk]), fetch_redirect_response=False,
        )

    def test_report_shows_import_links_only_to_the_instructor(self):
        url = reverse("course_report", args=[self.offering.pk])
        import_url = reverse("grade_import", args=[self.midterm.pk])
        self.client.force_login(self.teacher)
        self.assertContains(self.client.get(url), import_url)
        self.client.force_login(self.head)
        self.assertNotContains(self.client.get(url), import_url)

    def test_logged_out_is_sent_to_login(self):
        response = self.client.get(reverse("home"))

        self.assertRedirects(response, f"{reverse('login')}?next=/", fetch_redirect_response=False)


class LoginViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="elif", password="s3cret-pw")

    def test_logged_out_user_is_sent_to_login_not_a_404(self):
        report_url = reverse("course_report", args=[1])
        response = self.client.get(report_url)

        self.assertRedirects(
            response, f"{reverse('login')}?next={report_url}", fetch_redirect_response=False,
        )

    def test_wrong_credentials_show_an_error(self):
        response = self.client.post(reverse("login"), {"username": "elif", "password": "wrong"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Wrong username or password")

    def test_correct_credentials_follow_next(self):
        report_url = reverse("course_report", args=[1])
        response = self.client.post(
            reverse("login"),
            {"username": "elif", "password": "s3cret-pw", "next": report_url},
        )

        self.assertRedirects(response, report_url, fetch_redirect_response=False)

    def test_next_to_another_site_is_ignored(self):
        response = self.client.post(
            reverse("login"),
            {"username": "elif", "password": "s3cret-pw", "next": "https://evil.example/"},
        )

        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)

    def test_logout_needs_a_post(self):
        self.client.force_login(self.user)

        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)

    def test_404_uses_the_page_frame(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("course_report", args=[999]))

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "aculator.css", status_code=404)
        self.assertContains(response, "Page not found", status_code=404)

    def test_logout_sends_back_to_login(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse("logout"))

        self.assertRedirects(response, reverse("login"))


class StudentProfileViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.term = Term.objects.create(year=2026, season=Term.Season.FALL)
        cls.po1 = ProgramOutcome.objects.create(code="PO1")
        cls.component = POComponent.objects.create(program_outcome=cls.po1, code="a")

        cls.course = Course.objects.create(code="CSE311", name="Software Engineering", ects=6)
        cls.offering = CourseOffering.objects.create(course=cls.course, term=cls.term)
        cls.lo1 = LearningOutcome.objects.create(offering=cls.offering, code="LO1")
        cls.assessment = Assessment.objects.create(offering=cls.offering, name="Midterm", max_score=D("100"))
        AssessmentLOWeight.objects.create(assessment=cls.assessment, learning_outcome=cls.lo1, weight=D("1"))
        # A second assessment with the same score for everyone, so every PO1
        # rests on two assessments and is shown as a number, not as thin evidence (#42).
        cls.final = Assessment.objects.create(offering=cls.offering, name="Final", max_score=D("100"))
        AssessmentLOWeight.objects.create(assessment=cls.final, learning_outcome=cls.lo1, weight=D("1"))
        LOPOWeight.objects.create(learning_outcome=cls.lo1, component=cls.component, weight=1)

        cls.elif_ = get_user_model().objects.create_user(
            username="elif", first_name="Elif", last_name="Demir",
        )
        cls.elif_.groups.add(Group.objects.get(name=STUDENT))
        enrollment = Enrollment.objects.create(offering=cls.offering, student=cls.elif_)
        Grade.objects.create(enrollment=enrollment, assessment=cls.assessment, score=D("90"))
        Grade.objects.create(enrollment=enrollment, assessment=cls.final, score=D("90"))

        cls.can = get_user_model().objects.create_user(username="can")
        cls.can.groups.add(Group.objects.get(name=STUDENT))
        can_enrollment = Enrollment.objects.create(offering=cls.offering, student=cls.can)
        Grade.objects.create(enrollment=can_enrollment, assessment=cls.assessment, score=D("50"))
        Grade.objects.create(enrollment=can_enrollment, assessment=cls.final, score=D("50"))

        # Three more classmates at 70, so five students have a PO1 score and
        # the department mean (90 + 50 + 3 * 70) / 5 = 70 may be shown.
        for i in range(3):
            classmate = get_user_model().objects.create_user(username=f"classmate{i}")
            classmate.groups.add(Group.objects.get(name=STUDENT))
            enrollment = Enrollment.objects.create(offering=cls.offering, student=classmate)
            Grade.objects.create(enrollment=enrollment, assessment=cls.assessment, score=D("70"))
            Grade.objects.create(enrollment=enrollment, assessment=cls.final, score=D("70"))

        cls.teacher = get_user_model().objects.create_user(username="teacher")
        cls.teacher.groups.add(Group.objects.get(name=INSTRUCTOR))
        cls.offering.instructors.add(cls.teacher)

        cls.other_teacher = get_user_model().objects.create_user(username="other-teacher")
        cls.other_teacher.groups.add(Group.objects.get(name=INSTRUCTOR))

        cls.head = get_user_model().objects.create_user(username="head")
        cls.head.groups.add(Group.objects.get(name=HEAD))

        # The department average (#14) reads the materialized view (#9), not live grades.
        refresh_materialized_views()

    def test_student_sees_their_own_score_and_the_department_average(self):
        self.client.force_login(self.elif_)

        response = self.client.get(reverse("student_profile", args=[self.elif_.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PO1")
        self.assertContains(response, "90.0")
        self.assertContains(response, "70.0")  # average of 90 (Elif) and 50 (Can)

    def test_below_target_is_red(self):
        self.client.force_login(self.can)

        response = self.client.get(reverse("student_profile", args=[self.can.pk]))

        self.assertContains(response, "score below-target")
        self.assertContains(response, "PO1.a below 70")

    @override_settings(PO_TARGET="40")
    def test_below_the_mean_but_on_target_is_black_not_red(self):
        self.client.force_login(self.can)

        response = self.client.get(reverse("student_profile", args=[self.can.pk]))

        self.assertContains(response, "score below-mean")
        self.assertNotContains(response, "below-target")

    def test_profile_links_each_score_to_its_explanation(self):
        self.client.force_login(self.elif_)

        response = self.client.get(reverse("student_profile", args=[self.elif_.pk]))

        self.assertContains(response, reverse("po_detail", args=[self.elif_.pk, "PO1"]))
        self.assertContains(response, 'id="ring-PO1"')

    def test_detail_splits_the_score_into_grades(self):
        self.client.force_login(self.elif_)

        response = self.client.get(reverse("po_detail", args=[self.elif_.pk, "PO1"]))

        self.assertContains(response, "90.0 = Midterm")
        self.assertContains(response, 'id="slope-data"')

    def test_detail_follows_the_profile_rules(self):
        url = reverse("po_detail", args=[self.elif_.pk, "PO1"])
        for user, status in ((self.can, 404), (self.other_teacher, 404), (self.teacher, 200), (self.head, 200)):
            self.client.force_login(user)
            with self.subTest(user=user.username):
                self.assertEqual(self.client.get(url).status_code, status)
        self.client.force_login(self.elif_)
        self.assertEqual(self.client.get(reverse("po_detail", args=[self.elif_.pk, "PO9"])).status_code, 404)

    def test_equal_to_the_average_is_not_flagged(self):
        # Everyone scored 90, so Elif's PO1 is the department average.
        Grade.objects.update(score=D("90"))
        refresh_materialized_views()
        self.client.force_login(self.elif_)

        response = self.client.get(reverse("student_profile", args=[self.elif_.pk]))

        self.assertContains(response, "department 90.0")
        self.assertNotContains(response, "score below-")

    def test_too_few_students_give_no_department_figure(self):
        # With two students a mean gives the other one's score away; four is still too few.
        Grade.objects.filter(enrollment__student=self.can).delete()
        refresh_materialized_views()
        self.client.force_login(self.elif_)

        response = self.client.get(reverse("student_profile", args=[self.elif_.pk]))

        self.assertContains(response, "90.0")
        self.assertNotContains(response, "department 75.0")
        self.assertContains(response, "too few students")
        self.assertNotContains(response, "score below-")

    def test_missing_scores_are_named_for_screen_readers(self):
        Grade.objects.filter(enrollment__student=self.elif_).delete()
        self.client.force_login(self.elif_)

        response = self.client.get(reverse("student_profile", args=[self.elif_.pk]))

        self.assertContains(response, '<span class="sr-only">no evidence</span>')

    def test_instructor_sees_only_the_courses_they_teach(self):
        # Elif also takes CSE312 (4 ECTS) with another instructor and scored 10 there.
        other = CourseOffering.objects.create(
            course=Course.objects.create(code="CSE312", name="Databases", ects=4), term=self.term,
        )
        other.instructors.add(self.other_teacher)
        lo = LearningOutcome.objects.create(offering=other, code="LO1")
        final = Assessment.objects.create(offering=other, name="Final", max_score=D("100"))
        AssessmentLOWeight.objects.create(assessment=final, learning_outcome=lo, weight=D("1"))
        LOPOWeight.objects.create(learning_outcome=lo, component=self.component, weight=1)
        enrollment = Enrollment.objects.create(offering=other, student=self.elif_)
        Grade.objects.create(enrollment=enrollment, assessment=final, score=D("10"))
        url = reverse("student_profile", args=[self.elif_.pk])

        # Both courses: (90 * 6 + 10 * 4) / 10 = 58
        self.client.force_login(self.elif_)
        self.assertContains(self.client.get(url), "58.0")
        self.client.force_login(self.head)
        self.assertContains(self.client.get(url), "58.0")

        # CSE311's instructor sees CSE311 only, and nothing from CSE312.
        self.client.force_login(self.teacher)
        response = self.client.get(url)
        self.assertContains(response, "90.0")
        self.assertNotContains(response, "58.0")
        self.assertContains(response, "the courses you teach")

    def test_one_assessment_shows_as_thin_evidence(self):
        Grade.objects.filter(enrollment__student=self.can, assessment=self.final).delete()
        self.client.force_login(self.can)

        response = self.client.get(reverse("student_profile", args=[self.can.pk]))

        self.assertContains(response, 'class="score thin"')
        self.assertNotContains(response, "below-target")
        self.assertNotContains(response, 'id="ring-PO1"')

    def test_instructor_of_a_shared_course_can_view_the_profile(self):
        self.client.force_login(self.teacher)

        response = self.client.get(reverse("student_profile", args=[self.elif_.pk]))

        self.assertEqual(response.status_code, 200)

    def test_unrelated_instructor_gets_404(self):
        self.client.force_login(self.other_teacher)

        response = self.client.get(reverse("student_profile", args=[self.elif_.pk]))

        self.assertEqual(response.status_code, 404)

    def test_another_student_cannot_view_the_profile(self):
        self.client.force_login(self.can)

        response = self.client.get(reverse("student_profile", args=[self.elif_.pk]))

        self.assertEqual(response.status_code, 404)

    def test_head_can_view_any_profile(self):
        self.client.force_login(self.head)

        response = self.client.get(reverse("student_profile", args=[self.can.pk]))

        self.assertEqual(response.status_code, 200)

    def test_logged_out_is_sent_to_login(self):
        response = self.client.get(reverse("student_profile", args=[self.elif_.pk]))

        self.assertEqual(response.status_code, 302)
