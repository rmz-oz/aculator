from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.test import TestCase

from . import access
from .models import Assessment, Course, CourseOffering, Enrollment, Grade, Term


class AccessTests(TestCase):
    """Two offerings, one instructor each, two students in different courses."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        groups = {name: Group.objects.get(name=name) for name in access.ROLES}

        def user(name, *roles, **extra):
            u = User.objects.create_user(username=name, **extra)
            u.groups.add(*(groups[r] for r in roles))
            return u

        cls.elif_ = user("elif", access.STUDENT)
        cls.mert = user("mert", access.STUDENT)
        cls.ayse = user("ayse", access.INSTRUCTOR)
        cls.kemal = user("kemal", access.INSTRUCTOR)
        cls.head = user("head", access.HEAD)
        cls.nobody = user("nobody")
        cls.admin = user("admin", is_superuser=True)
        cls.inactive = user("inactive", access.HEAD, is_active=False)

        term = Term.objects.create(year=2026, season=Term.Season.FALL)
        cls.cse321 = CourseOffering.objects.create(
            course=Course.objects.create(code="CSE321", name="Data Systems", ects=6), term=term
        )
        cls.cse311 = CourseOffering.objects.create(
            course=Course.objects.create(code="CSE311", name="Software", ects=6), term=term
        )
        cls.cse321.instructors.add(cls.ayse)
        cls.cse311.instructors.add(cls.kemal)

        for offering, student in ((cls.cse321, cls.elif_), (cls.cse311, cls.mert)):
            enrollment = Enrollment.objects.create(offering=offering, student=student)
            exam = Assessment.objects.create(offering=offering, name="Midterm")
            Grade.objects.create(enrollment=enrollment, assessment=exam, score=80)

    def students_in(self, qs, path):
        return set(qs.values_list(path, flat=True))

    def test_role_groups_exist_after_migrate(self):
        self.assertEqual(
            set(Group.objects.values_list("name", flat=True)) & set(access.ROLES),
            set(access.ROLES),
        )

    def test_roles(self):
        self.assertEqual(access.role_of(self.elif_), access.STUDENT)
        self.assertEqual(access.role_of(self.ayse), access.INSTRUCTOR)
        self.assertEqual(access.role_of(self.head), access.HEAD)
        self.assertEqual(access.role_of(self.admin), access.HEAD)
        self.assertIsNone(access.role_of(self.nobody))
        self.assertIsNone(access.role_of(self.inactive))
        self.assertIsNone(access.role_of(AnonymousUser()))

    def test_widest_role_wins(self):
        self.mert.groups.add(Group.objects.get(name=access.INSTRUCTOR))
        self.assertEqual(access.role_of(self.mert), access.INSTRUCTOR)

    def test_student_sees_only_own_data(self):
        self.assertEqual(list(access.visible_offerings(self.elif_)), [self.cse321])
        self.assertEqual(self.students_in(access.visible_enrollments(self.elif_), "student"), {self.elif_.pk})
        self.assertEqual(
            self.students_in(access.visible_grades(self.elif_), "enrollment__student"), {self.elif_.pk}
        )

    def test_instructor_sees_only_their_offerings(self):
        self.assertEqual(list(access.visible_offerings(self.ayse)), [self.cse321])
        self.assertEqual(self.students_in(access.visible_enrollments(self.ayse), "student"), {self.elif_.pk})
        self.assertEqual(
            self.students_in(access.visible_grades(self.ayse), "enrollment__student"), {self.elif_.pk}
        )

    def test_head_sees_everything(self):
        for viewer in (self.head, self.admin):
            self.assertEqual(access.visible_offerings(viewer).count(), 2)
            self.assertEqual(access.visible_enrollments(viewer).count(), 2)
            self.assertEqual(access.visible_grades(viewer).count(), 2)

    def test_no_role_sees_nothing(self):
        for viewer in (self.nobody, self.inactive, AnonymousUser()):
            self.assertFalse(access.visible_offerings(viewer).exists())
            self.assertFalse(access.visible_enrollments(viewer).exists())
            self.assertFalse(access.visible_grades(viewer).exists())

    def test_student_offerings_not_duplicated(self):
        # Two enrollments would not happen (unique), but a join on a second
        # relation could still repeat rows; distinct() keeps the list clean.
        self.assertEqual(access.visible_offerings(self.elif_).count(), 1)

    def test_can_view_student(self):
        cases = (
            (self.elif_, self.elif_, True),
            (self.elif_, self.mert, False),
            (self.ayse, self.elif_, True),
            (self.ayse, self.mert, False),
            (self.kemal, self.mert, True),
            (self.head, self.mert, True),
            (self.nobody, self.elif_, False),
            (self.inactive, self.elif_, False),
        )
        for viewer, student, expected in cases:
            with self.subTest(viewer=viewer.username, student=student.username):
                self.assertEqual(access.can_view_student(viewer, student), expected)
