"""Learning outcomes and LO-PO levels from the Bologna catalogue (#85, #86, #87).

The fixtures are real Acıbadem catalogue pages, cut down to the three tables
the parser reads (no instructor names): CSE 220 and MAT 241 have a filled
LO-PO table, CSE 301 an empty one, CSE 332 the same row for every LO.
"""

from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from . import bologna
from .access import INSTRUCTOR
from .bologna import CatalogueError, parse_course_page
from .models import Course, CourseOffering, LearningOutcome, LOPOWeight, POComponent, ProgramOutcome, Term

FIXTURES = Path(__file__).parent / "fixtures" / "bologna"


def page(name):
    return (FIXTURES / f"{name}.html").read_text(encoding="utf-8")


def synthetic(rows, los=("First outcome", "Second outcome")):
    """A course page with two LOs and a P1 to P3 table, in the catalogue's layout."""
    lo_rows = "".join(f"<tr><td>{i}</td><td>{text}</td></tr>" for i, text in enumerate(los, 1))
    table_rows = "".join(
        "<tr><td>" + label + "</td>" + "".join(f"<td>{v}</td>" for v in values) + "</tr>" for label, values in rows
    )
    return (
        '<table id="grdOgrenmeCiktilari"><tr><th>Sıra No</th><th>Açıklama</th></tr>' + lo_rows + "</table>"
        '<table id="grdProgCiktiKatki"><tr><th></th><th>P1</th><th>P2</th><th>P3</th></tr>' + table_rows + "</table>"
    )


CSE220_LEVELS = {
    (0, 1): 4, (0, 2): 4, (0, 3): 4, (0, 4): 4, (0, 6): 4, (0, 10): 4,
    (1, 1): 4, (1, 4): 4,
    (2, 1): 4,
    (3, 4): 4, (3, 6): 4, (3, 7): 4, (3, 10): 4,
}


class ParseTests(TestCase):
    def test_cse220_in_english(self):
        syllabus = parse_course_page(page("cse220_en"))
        self.assertEqual((syllabus.code, syllabus.title, syllabus.ects), ("CSE 220", "Web Programming", "6"))
        self.assertEqual(syllabus.los, [
            "Get hands-on experience on web development.",
            "Learn the skills to do web development with Django.",
            "Get a grasp of the Model View Controller (MVC) architecture.",
            "Acquire the skills to build a website and to present it to the class.",
        ])
        self.assertEqual(syllabus.pos, list(range(1, 12)))
        self.assertEqual(syllabus.levels, CSE220_LEVELS)
        self.assertEqual(syllabus.problems, [])

    def test_cse220_in_turkish_has_the_same_levels(self):
        syllabus = parse_course_page(page("cse220_tr"))
        self.assertEqual(syllabus.los[0], "Web uygulaması geliştirme pratiği kazanmak")
        self.assertEqual(syllabus.levels, CSE220_LEVELS)

    def test_mat241(self):
        syllabus = parse_course_page(page("mat241_en"))
        self.assertEqual(len(syllabus.los), 4)
        self.assertEqual(syllabus.levels, {
            (0, 1): 5, (0, 2): 3, (1, 1): 4, (1, 2): 3, (2, 1): 4, (2, 2): 4, (3, 1): 4, (3, 2): 4,
        })

    def test_empty_table_is_said(self):
        syllabus = parse_course_page(page("cse301_en"))
        self.assertEqual(len(syllabus.los), 3)
        self.assertEqual(syllabus.levels, {})
        self.assertEqual(syllabus.problems, ["The LO-PO table in the catalogue is empty. Enter the levels below."])

    def test_the_same_row_for_every_lo_is_flagged(self):
        syllabus = parse_course_page(page("cse332_en"))
        self.assertEqual(syllabus.levels, {(0, 1): 4, (1, 1): 4, (2, 1): 4})
        self.assertIn("usually copied", syllabus.problems[0])

    def test_wrong_cells_are_listed_and_left_empty(self):
        html = page("cse220_en").replace('lblP1_1">4<', 'lblP1_1">X<').replace('lblP2_1">4<', 'lblP2_1">7<')
        syllabus = parse_course_page(html)
        self.assertEqual(len(syllabus.levels), len(CSE220_LEVELS) - 2)
        self.assertEqual(syllabus.problems, [
            'C1, P1: "X" is not a level from 1 to 5, left empty.',
            'C1, P2: "7" is not a level from 1 to 5, left empty.',
        ])

    def test_whole_course_row_only_goes_to_every_lo(self):
        syllabus = parse_course_page(synthetic([("Tüm", ["5", "", "2"]), ("Ö1", ["", "", ""]), ("Ö2", ["", "", ""])]))
        self.assertEqual(syllabus.levels, {(0, 1): 5, (0, 3): 2, (1, 1): 5, (1, 3): 2})
        self.assertIn("whole course only", syllabus.problems[-1])

    def test_more_rows_than_los(self):
        syllabus = parse_course_page(synthetic([("Ö1", ["1", "", ""]), ("Ö2", ["", "2", ""]), ("Ö3", ["", "", "3"])]))
        self.assertEqual(syllabus.levels, {(0, 1): 1, (1, 2): 2})
        self.assertIn("3 rows but the course lists 2", syllabus.problems[0])

    def test_not_a_course_page(self):
        with self.assertRaises(CatalogueError):
            parse_course_page("<html><body>Sayfa bulunamadı</body></html>")

    def test_fetch_finds_the_course_id_by_code(self):
        listing = ('<a onclick="return prolizOpenCourseDetails(273623);" id="grdBolognaDersler_btnDersKod_7" '
                   'href="#"><font size="2">CSE 220</font></a>')
        urls = []

        def get(url):
            urls.append(url)
            return listing if "progCourses" in url else page("cse220_en")

        with mock.patch.object(bologna, "_get", side_effect=get), mock.patch.object(bologna.cache, "get", return_value=None):
            syllabus = bologna.fetch_course("CSE220")
            self.assertEqual(syllabus.levels, CSE220_LEVELS)
            self.assertIn("curCourse=273623", urls[-1])
            with self.assertRaises(CatalogueError):
                bologna.fetch_course("CSE999")


class SyllabusImportViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        term = Term.objects.create(year=2026, season=Term.Season.FALL)
        course = Course.objects.create(code="CSE220", name="Web Programming", ects=6)
        cls.offering = CourseOffering.objects.create(course=course, term=term)
        cls.pos = {}
        for n in range(1, 12):
            po = ProgramOutcome.objects.create(code=f"PO{n}")
            POComponent.objects.create(program_outcome=po, code="a")
            if n == 1:
                POComponent.objects.create(program_outcome=po, code="b")
            cls.pos[n] = po
        users = get_user_model().objects
        cls.teacher = users.create_user("teacher")
        cls.teacher.groups.add(Group.objects.get_or_create(name=INSTRUCTOR)[0])
        cls.offering.instructors.add(cls.teacher)
        cls.other = users.create_user("other")
        cls.other.groups.add(Group.objects.get_or_create(name=INSTRUCTOR)[0])
        cls.url = reverse("syllabus_import", args=[cls.offering.pk])

    def upload(self, name="cse220_en", user=None):
        self.client.force_login(user or self.teacher)
        return self.client.post(self.url, {
            "action": "upload",
            "page": SimpleUploadedFile(f"{name}.html", page(name).encode(), content_type="text/html"),
        })

    def form(self, response):
        """The preview form as the browser would send it back."""
        data = {"action": "save", "token": response.context["token"], "lo_text": [r["text"] for r in response.context["rows"]]}
        for row in response.context["rows"]:
            for po, level in row["levels"]:
                data[f"level_{row['index']}_{po.pk}"] = str(level or "")
        return data

    def test_only_the_instructor_gets_in(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.upload(user=self.other).status_code, 404)

    def test_reading_saves_nothing(self):
        response = self.upload()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Learn the skills to do web development with Django.")
        self.assertEqual(LearningOutcome.objects.count(), 0)
        self.assertEqual(LOPOWeight.objects.count(), 0)

    def test_save_writes_what_the_instructor_sent(self):
        data = self.form(self.upload())
        data["lo_text"][1] = "Build web applications with Django."
        data[f"level_0_{self.pos[2].pk}"] = ""  # removed by the instructor
        data[f"level_2_{self.pos[5].pk}"] = "2"  # added by the instructor
        response = self.client.post(self.url, data)
        self.assertContains(response, "4 learning outcomes saved")
        los = {lo.code: lo for lo in LearningOutcome.objects.filter(offering=self.offering)}
        self.assertEqual(los["LO2"].description, "Build web applications with Django.")
        levels = {(w.learning_outcome.code, w.component.program_outcome.code, w.component.code): w.weight
                  for w in LOPOWeight.objects.select_related("learning_outcome", "component__program_outcome")}
        self.assertEqual(levels[("LO1", "PO1", "a")], 4)
        self.assertEqual(levels[("LO1", "PO1", "b")], 4)  # every component of the PO
        self.assertNotIn(("LO1", "PO2", "a"), levels)
        self.assertEqual(levels[("LO3", "PO5", "a")], 2)
        self.assertEqual(len(levels), 13 - 1 + 1 + 3)  # PO1 has two components, in LO1, LO2 and LO3

    def test_existing_los_are_updated_and_others_kept(self):
        LearningOutcome.objects.create(offering=self.offering, code="LO1", description="Old text")
        extra = LearningOutcome.objects.create(offering=self.offering, code="LO9", description="Kept")
        response = self.upload()
        self.assertContains(response, "Now: Old text")
        self.assertContains(response, "LO9 stay as they are.")
        self.client.post(self.url, self.form(response))
        self.assertEqual(LearningOutcome.objects.get(offering=self.offering, code="LO1").description,
                         "Get hands-on experience on web development.")
        self.assertTrue(LearningOutcome.objects.filter(pk=extra.pk).exists())

    def test_a_change_after_the_preview_is_refused(self):
        data = self.form(self.upload())
        LearningOutcome.objects.create(offering=self.offering, code="LO1", description="Typed in the admin meanwhile")
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(LearningOutcome.objects.get().description, "Typed in the admin meanwhile")

    def test_tampered_token_and_bad_levels_are_refused(self):
        data = self.form(self.upload())
        self.assertEqual(self.client.post(self.url, {**data, "token": data["token"] + "x"}).status_code, 400)
        data[f"level_0_{self.pos[1].pk}"] = "9"
        response = self.client.post(self.url, data)
        self.assertContains(response, "the level must be 1 to 5", status_code=400)
        self.assertEqual(LearningOutcome.objects.count(), 0)

    def test_page_of_another_course_is_flagged(self):
        response = self.upload("mat241_en")
        self.assertContains(response, "This page is for MAT 241, not CSE220.")

    def test_unreachable_catalogue_saves_nothing(self):
        self.client.force_login(self.teacher)
        with mock.patch.object(bologna, "_get", side_effect=CatalogueError("The course catalogue did not answer.")):
            response = self.client.post(self.url, {"action": "fetch"})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "did not answer", status_code=400)

    def test_a_different_course_name_is_flagged(self):
        Course.objects.filter(pk=self.offering.course_id).update(name="Software Engineering")
        response = self.upload()
        self.assertContains(response, "The catalogue calls this course Web Programming, here it is Software Engineering.")
