"""What a real department's data looks like, on top of the clean fake data (#100).

fake_data gives every student every grade, all of them plausible. A real
department has typing mistakes, a class graded on the wrong scale, missing
finals, a term still in progress, a PO no course measures, a 3 student
elective and a 200 student first year course. apply() puts those in, the same
way every time for the same seed, and returns where each one is, for
docs/demo_scenarios.md. The tests keep using the clean data.

Each scenario works on its own offering where it changes a whole class, so
one does not hide another.
"""

import random
from decimal import Decimal
from itertools import pairwise

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction

from .access import INSTRUCTOR, STUDENT
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
    Term,
)

# Marks a database that already has the scenarios; apply() runs once.
ELECTIVE = ("CSE491", "Selected Topics in Machine Learning", 5)
CURRENT_TERM = (2026, "fall")
UNMEASURED_PO = "PO11"
ASSESSMENTS = (("Midterm", 100), ("Final", 100), ("Quiz", 20), ("Project", 100))

# Who teaches what. Course code -> instructors by year; a list is two people.
FACULTY = {
    "ayse.kaya": ("Ayşe", "Kaya"),
    "mehmet.oz": ("Mehmet", "Öz"),
    "zeynep.arslan": ("Zeynep", "Arslan"),
    "can.yildiz": ("Can", "Yıldız"),
    "elif.sahin": ("Elif", "Şahin"),
    "burak.celik": ("Burak", "Çelik"),
}
TEACHES = {
    "CSE101": "ayse.kaya",
    "CSE102": "ayse.kaya",
    "CSE201": "mehmet.oz",
    "CSE202": "mehmet.oz",
    "CSE203": "zeynep.arslan",
    "CSE301": "can.yildiz",
    "CSE302": "elif.sahin",
    "CSE303": "burak.celik",
}
# From 2025 on, CSE302 moves to Burak Çelik: the old instructor keeps access (decision 0007 has no dates).
HANDOVER = ("CSE302", 2025, "burak.celik")
D = Decimal


def applied():
    return Course.objects.filter(code=ELECTIVE[0]).exists()


def apply(seed=42):
    """Add every scenario. Returns [(scenario, where)], or [] if already applied."""
    if applied():
        return []
    with transaction.atomic():
        report = _Scenarios(seed).run()
    refresh_materialized_views()
    return report


class _Scenarios:
    def __init__(self, seed):
        self.seed = seed
        self.report = []
        self.used = set()  # offerings a whole-class scenario already changed
        self.User = get_user_model()
        self.student_group = Group.objects.get_or_create(name=STUDENT)[0]

    def rng(self, *key):
        return random.Random(":".join(str(k) for k in (self.seed, "scenario", *key)))

    def note(self, scenario, where):
        self.report.append((scenario, where))

    def offering(self, code, year, season):
        offering = CourseOffering.objects.select_related("course", "term").get(
            course__code=code, term__year=year, term__season=season
        )
        self.used.add(offering.pk)
        return offering

    def grades(self, offering, name):
        return Grade.objects.filter(assessment__offering=offering, assessment__name=name).select_related(
            "enrollment__student"
        ).order_by("enrollment__student__username")

    def run(self):
        self.faculty()
        self.term_in_progress()
        self.wrong_scale()
        self.wrong_assessment()
        self.sorted_column()
        self.inflation_and_two_groups()
        self.missing_mapping()
        self.unmeasured_po()
        self.small_elective()
        self.big_first_year_course()
        self.summer_school()
        self.transfer_and_exchange()
        self.withdrawals()
        self.missing_finals()
        self.zero_instead_of_absent()
        self.typos()
        # Last, so the scenarios above pick the same students as before.
        self.retakes()
        self.makeups()
        return self.report

    # People

    def faculty(self):
        group = Group.objects.get_or_create(name=INSTRUCTOR)[0]
        people = {}
        for username, (first, last) in FACULTY.items():
            user, created = self.User.objects.get_or_create(
                username=username, defaults={"first_name": first, "last_name": last}
            )
            if created:
                user.set_unusable_password()
                user.save(update_fields=["password"])
            user.groups.add(group)
            people[username] = user
        for offering in CourseOffering.objects.select_related("course", "term"):
            teacher = TEACHES.get(offering.course.code)
            if teacher:
                offering.instructors.add(people[teacher])
        code, year, new = HANDOVER
        for offering in CourseOffering.objects.filter(course__code=code, term__year__gte=year):
            offering.instructors.add(people[new])
        self.note("Instructor handover", f"{code} from {year}: Elif Şahin and Burak Çelik both listed, "
                  "the one who left still sees the grades")
        self.people = people

    # Whole classes

    def term_in_progress(self):
        year, season = CURRENT_TERM
        deleted = Grade.objects.filter(
            assessment__offering__term__year=year,
            assessment__offering__term__season=season,
        ).exclude(assessment__name="Midterm")
        count = deleted.count()
        deleted.delete()
        self.used.update(CourseOffering.objects.filter(term__year=year, term__season=season).values_list("pk", flat=True))
        self.note("Term in progress", f"{year} Fall: only Midterm entered, {count} later grades not there yet")

    def wrong_scale(self):
        offering = self.offering("CSE202", 2024, "spring")
        changed = []
        for grade in self.grades(offering, "Project"):
            grade.score = (grade.score / 5).quantize(D("0.01"))
            changed.append(grade)
        Grade.objects.bulk_update(changed, ["score"])
        self.note("Wrong scale", f"{offering}: Project typed out of 20 into an assessment out of 100, "
                  f"{len(changed)} students around 15/100")

    def wrong_assessment(self):
        offering = self.offering("CSE102", 2025, "fall")
        midterm = {g.enrollment_id: g.score for g in self.grades(offering, "Midterm")}
        changed = []
        for grade in self.grades(offering, "Final"):
            if grade.enrollment_id in midterm:
                grade.score = midterm[grade.enrollment_id]
                changed.append(grade)
        Grade.objects.bulk_update(changed, ["score"])
        self.note("Wrong assessment", f"{offering}: the Midterm list imported as the Final, "
                  f"{len(changed)} Finals equal to the Midterm")

    def sorted_column(self):
        offering = self.offering("CSE201", 2024, "fall")
        grades = list(self.grades(offering, "Midterm"))
        scores = sorted((g.score for g in grades), reverse=True)
        for grade, score in zip(grades, scores):
            grade.score = score
        Grade.objects.bulk_update(grades, ["score"])
        self.note("Score column sorted alone", f"{offering}: Midterm scores sorted high to low against the "
                  "student list, the class mean did not change")

    def inflation_and_two_groups(self):
        offering = self.offering("CSE203", 2025, "spring")
        changed = []
        for grade in Grade.objects.filter(assessment__offering=offering).select_related("assessment"):
            grade.score = min(grade.score * D("1.18"), grade.assessment.max_score).quantize(D("0.01"))
            changed.append(grade)
        Grade.objects.bulk_update(changed, ["score"])
        self.note("Grade inflation", f"{offering}: every grade 18% higher, most students far above target")

        offering = self.offering("CSE202", 2025, "fall")
        changed = []
        for grade in Grade.objects.filter(assessment__offering=offering).select_related("enrollment__student"):
            if self.rng("two-groups", grade.enrollment.student.username).random() < 0.5:
                grade.score = (grade.score * D("0.55")).quantize(D("0.01"))
                changed.append(grade)
        Grade.objects.bulk_update(changed, ["score"])
        self.note("Two groups in one class", f"{offering}: half the class around 40, half around 75, "
                  "the mean looks like an ordinary class")

    # Outcomes and mapping

    def missing_mapping(self):
        offering = self.offering("CSE303", 2026, "spring")
        LearningOutcome.objects.filter(offering=offering).delete()
        self.note("No learning outcomes yet", f"{offering}: grades but no LOs, so no LO or PO scores")

        offering = self.offering("CSE301", 2025, "spring")
        lo = LearningOutcome.objects.get(offering=offering, code="LO3")
        LOPOWeight.objects.filter(learning_outcome=lo).delete()
        self.note("LO without PO mapping", f"{offering}: LO3 has scores but feeds no PO")

    def unmeasured_po(self):
        count, _ = LOPOWeight.objects.filter(component__program_outcome__code=UNMEASURED_PO).delete()
        self.note("PO no course measures", f"{UNMEASURED_PO}: {count} LO links removed, no evidence anywhere")

    # Class sizes and odd terms

    def build_offering(self, offering):
        """LOs, assessments and weights like fake_data, for an offering created here."""
        r = self.rng("build", offering.course.code, offering.term_id)
        assessments = [
            Assessment.objects.get_or_create(offering=offering, name=name, defaults={"max_score": D(m)})[0]
            for name, m in ASSESSMENTS
        ]
        components = list(POComponent.objects.exclude(program_outcome__code=UNMEASURED_PO))
        for i in range(1, 4):
            lo = LearningOutcome.objects.create(offering=offering, code=f"LO{i}", description=f"Learning outcome {i}")
            for assessment in r.sample(assessments, k=2):
                AssessmentLOWeight.objects.create(
                    assessment=assessment, learning_outcome=lo, weight=D(r.choice(["0.4", "0.5", "0.6", "1.0"]))
                )
            for component in r.sample(components, k=r.randint(1, 3)):
                LOPOWeight.objects.create(learning_outcome=lo, component=component, weight=r.randint(1, 5))
        return assessments

    def enroll(self, offering, students, level=70, spread=12):
        assessments = list(offering.assessments.all())
        grades = []
        for student in students:
            enrollment, _ = Enrollment.objects.get_or_create(offering=offering, student=student)
            r = self.rng("grade", student.username, offering.pk)
            mean = min(max(self.rng("level", student.username).gauss(level, spread), 25), 98)
            for assessment in assessments:
                percent = D(str(round(min(max(r.gauss(mean, 8), 0), 100), 1)))
                grades.append(Grade(
                    enrollment=enrollment,
                    assessment=assessment,
                    term_id=offering.term_id,
                    score=(assessment.max_score * percent / 100).quantize(D("0.01")),
                ))
        Grade.objects.bulk_create(grades, ignore_conflicts=True)

    def new_students(self, start, count, first="Student"):
        users = []
        for i in range(start, start + count):
            username = f"fake_student_{i:04d}"
            user, created = self.User.objects.get_or_create(
                username=username,
                defaults={"first_name": f"{first}{i}", "last_name": "Demo", "email": f"{username}@example.com"},
            )
            if created:
                user.set_unusable_password()
                user.save(update_fields=["password"])
            users.append(user)
        self.student_group.user_set.add(*users)
        return users

    def students_without(self, code, count, key):
        taken = Enrollment.objects.filter(offering__course__code=code).values("student")
        pool = list(self.User.objects.filter(username__startswith="fake_student_", username__lt="fake_student_0401")
                    .exclude(pk__in=taken).order_by("username"))
        return self.rng(key).sample(pool, k=min(count, len(pool)))

    def small_elective(self):
        code, name, ects = ELECTIVE
        course = Course.objects.create(code=code, name=name, ects=ects)
        term = Term.objects.get(year=2025, season="spring")
        offering = CourseOffering.objects.create(course=course, term=term)
        offering.instructors.add(self.people["zeynep.arslan"])
        self.build_offering(offering)
        students = sorted(self.rng("elective").sample(
            list(self.User.objects.filter(username__startswith="fake_student_", username__lt="fake_student_0401")), k=3
        ), key=lambda u: u.username)
        self.enroll(offering, students, level=80, spread=6)
        self.note("3 student elective", f"{offering}: {', '.join(s.username for s in students)}; "
                  "one student moves the class mean by a third")

    def big_first_year_course(self):
        offering = self.offering("CSE101", 2025, "fall")
        before = offering.enrollments.count()
        newcomers = self.new_students(401, 200 - before)
        self.enroll(offering, newcomers, level=66, spread=15)
        self.note("200 student first year course", f"{offering}: {before} students plus {len(newcomers)} first "
                  f"years (fake_student_0401 to {newcomers[-1].username}) who have only this course")
        self.next_student = 401 + len(newcomers)

    def summer_school(self):
        for year, code, count in ((2024, "CSE102", 6), (2025, "CSE201", 8)):
            term, _ = Term.objects.get_or_create(year=year, season="summer")
            offering = CourseOffering.objects.create(course=Course.objects.get(code=code), term=term)
            offering.instructors.add(self.people[TEACHES[code]])
            self.used.add(offering.pk)
            self.build_offering(offering)
            self.enroll(offering, self.students_without(code, count, f"summer-{code}"), level=62)
            self.note("Summer school", f"{offering}: {count} students, a short term with a small class")

    def transfer_and_exchange(self):
        start = self.next_student
        transfers = self.new_students(start, 15, first="Transfer")
        exchange = self.new_students(start + 15, 5, first="Erasmus")
        for i, student in enumerate(transfers):
            r = self.rng("transfer", student.username)
            offerings = CourseOffering.objects.filter(term__year__gte=2025, course__code__in=("CSE201", "CSE202", "CSE301", "CSE302")).exclude(
                term__year=CURRENT_TERM[0], term__season=CURRENT_TERM[1]).exclude(pk__in=self.used)
            for offering in r.sample(list(offerings.order_by("pk")), k=1 + i % 3):
                if not Enrollment.objects.filter(student=student, offering__course=offering.course).exists():
                    self.enroll(offering, [student])
        spring = CourseOffering.objects.filter(term__year=2025, term__season="spring", course__code__in=("CSE302", "CSE303"))
        for offering in spring.exclude(pk__in=self.used):
            self.enroll(offering, exchange, level=74)
        self.note("Transfer students", f"{transfers[0].username} to {transfers[-1].username}: 1 to 3 courses each, "
                  "most POs without evidence")
        self.note("Erasmus students", f"{exchange[0].username} to {exchange[-1].username}: two courses in 2025 "
                  "Spring, counted in the department means")

    # Single grades

    def finished_grades(self):
        """Grades of finished terms in offerings no whole-class scenario touched."""
        return (Grade.objects.exclude(assessment__offering__in=self.used)
                .exclude(assessment__offering__term__year=CURRENT_TERM[0], assessment__offering__term__season=CURRENT_TERM[1])
                .filter(enrollment__student__username__lt="fake_student_0401")
                .select_related("enrollment__student", "assessment__offering__course", "assessment__offering__term")
                .order_by("pk"))

    def withdrawals(self):
        enrollments = sorted({g.enrollment for g in self.finished_grades().filter(assessment__name="Midterm")},
                             key=lambda e: e.pk)
        left = self.rng("withdraw").sample(enrollments, k=len(enrollments) * 3 // 100)
        Grade.objects.filter(enrollment__in=left).exclude(assessment__name="Midterm").delete()
        self.withdrawn = {e.pk for e in left}
        example = left[0]
        self.note("Left after the midterm", f"{len(left)} enrollments with only a Midterm, e.g. "
                  f"{example.student.username} in {example.offering}")

    def missing_finals(self):
        finals = [g for g in self.finished_grades().filter(assessment__name="Final") if g.enrollment_id not in self.withdrawn]
        missing = self.rng("missing-final").sample(finals, k=min(8, len(finals)))
        Grade.objects.filter(pk__in=[g.pk for g in missing]).delete()
        self.skip = {g.enrollment_id for g in missing} | self.withdrawn
        self.note("Final row missing", "; ".join(
            f"{g.enrollment.student.username} {g.assessment.offering}" for g in missing[:3]) + f" and {len(missing) - 3} more")

    def zero_instead_of_absent(self):
        finals = [g for g in self.finished_grades().filter(assessment__name="Final") if g.enrollment_id not in self.skip]
        r = self.rng("absent")
        picked = r.sample(finals, k=len(finals) * 4 // 100)
        typed, marked = picked[: len(picked) // 2], picked[len(picked) // 2:]
        for grade in typed:
            grade.score = D(0)
        for grade in marked:
            grade.score, grade.status = D(0), Grade.Status.ABSENT
        Grade.objects.bulk_update(picked, ["score", "status"])
        self.skip |= {g.enrollment_id for g in picked}
        self.note("Absent typed as 0", f"{len(typed)} Finals saved as a graded 0, e.g. "
                  f"{typed[0].enrollment.student.username} in {typed[0].assessment.offering}")
        self.note("Absent marked properly", f"{len(marked)} Finals marked absent, e.g. "
                  f"{marked[0].enrollment.student.username} in {marked[0].assessment.offering}")

    def typos(self):
        candidates = [g for g in self.finished_grades().filter(assessment__max_score=100, score__gte=60, score__lt=99)
                      if g.enrollment_id not in self.skip]
        # A swap needs two different digits and no zero, or 66 stays 66 and 70 becomes 7.
        swappable = [g for g in candidates if len(set(str(int(g.score)))) == 2 and "0" not in str(int(g.score))]
        r = self.rng("typos")
        swaps = r.sample(swappable, k=min(6, len(swappable)))
        shifts = r.sample(rest := [g for g in candidates if g not in swaps], k=min(6, len(rest)))
        picked = [g for pair in zip(swaps, shifts) for g in pair]
        lines = []
        for i, grade in enumerate(picked):
            old = grade.score
            if i % 2 == 0:
                whole, _, rest = f"{old:.2f}".partition(".")
                grade.score = D(f"{whole[::-1]}.{rest}")  # 85.30 typed as 58.30
            else:
                grade.score = (old / 10).quantize(D("0.01"))  # 85.30 typed as 8.53
            lines.append(f"{grade.enrollment.student.username} {grade.assessment.offering} "
                         f"{grade.assessment.name} {old} as {grade.score}")
        Grade.objects.bulk_update(picked, ["score"])
        self.typo_lines = lines
        self.note("Typing mistakes", "; ".join(lines))

    # Retakes and makeups (#104, #105)

    def failing(self, offering):
        """Enrollments of a finished offering whose grades average under 50%, worst first."""
        totals = {}
        for grade in Grade.objects.filter(assessment__offering=offering).select_related("assessment", "enrollment"):
            got, out_of = totals.get(grade.enrollment, (D(0), D(0)))
            totals[grade.enrollment] = (got + grade.score, out_of + grade.assessment.max_score)
        low = [(got / out_of, e) for e, (got, out_of) in totals.items() if out_of and got / out_of < D("0.5")]
        return [e for _, e in sorted(low, key=lambda pair: (pair[0], pair[1].pk))]

    def retakes(self):
        """Students who failed a course and took it again the next time it ran."""
        lines = []
        for code in ("CSE201", "CSE202", "CSE301", "CSE302"):
            runs = list(CourseOffering.objects.filter(course__code=code).exclude(
                term__year=CURRENT_TERM[0], term__season=CURRENT_TERM[1]).select_related("term", "course"))
            runs.sort(key=lambda o: (o.term.year, {"spring": 1, "summer": 2, "fall": 3}[o.term.season]))
            for first, second in pairwise(runs):
                for enrollment in self.failing(first)[:2]:
                    if Enrollment.objects.filter(student=enrollment.student, offering=second).exists():
                        continue
                    self.enroll(second, [enrollment.student], level=72, spread=4)
                    lines.append(f"{enrollment.student.username} {code} {first.term} then {second.term}")
        if lines:
            self.note("Course retaken", f"{len(lines)} retakes, only the later attempt counts across courses, e.g. "
                      + "; ".join(lines[:3]))

    def makeups(self):
        """A Makeup that replaces the Final, taken by the students who failed it."""
        for code, year, season in (("CSE202", 2025, "fall"), ("CSE301", 2025, "spring")):
            offering = CourseOffering.objects.get(course__code=code, term__year=year, term__season=season)
            final = offering.assessments.get(name="Final")
            makeup = Assessment.objects.create(offering=offering, name="Makeup", replaces=final)
            AssessmentLOWeight.objects.bulk_create(
                AssessmentLOWeight(assessment=makeup, learning_outcome_id=w.learning_outcome_id, weight=w.weight)
                for w in final.lo_weights.all()
            )
            failed = [g for g in self.grades(offering, "Final") if g.score < final.max_score / 2]
            r = self.rng("makeup", offering.pk)
            grades = []
            for i, grade in enumerate(failed):
                if i % 5 == 4:
                    status, score = Grade.Status.ABSENT, D(0)  # signed up, did not come: the Final stays
                else:
                    status, score = Grade.Status.GRADED, D(str(round(r.uniform(35, 80), 1)))
                grades.append(Grade(enrollment=grade.enrollment, assessment=makeup, term_id=offering.term_id,
                                    status=status, score=score))
            Grade.objects.bulk_create(grades)
            lower = [g for g, f in zip(grades, failed) if g.status == Grade.Status.GRADED and g.score < f.score]
            self.note("Makeup exam", f"{offering}: {len(grades)} students took the Makeup, it replaces their Final"
                      + (f"; {lower[0].enrollment.student.username} scored lower and that counts" if lower else ""))
