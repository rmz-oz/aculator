"""Reading a course's learning outcomes and LO-PO table from the Bologna catalogue (#85, #86).

Acıbadem publishes every course in its Bologna information package, served by
Proliz OIBS (/oibs/bologna/progCourseDetails.aspx). The page has the learning
outcomes (table grdOgrenmeCiktilari) and "Dersin Program Çıktılarına Katkısı",
the contribution of each LO to each PO on a 1 to 5 scale (table
grdProgCiktiKatki): one row per LO (Ö1, Ö2, ... or C1, C2, ... in English) and
sometimes a "Tüm"/"All" row for the whole course. About 70 Turkish universities
use the same system, so this reads theirs too.

Nothing here writes to the database. Only the three tables are read: the page
also names the instructors, which is not kept anywhere (KVKK).
"""

import http.client
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser

from django.conf import settings
from django.core.cache import cache
from django.utils.translation import gettext as _

LEVELS = range(1, 6)
ALL_ROW = {"tüm", "all"}
# Short: the fetch runs inside the request, and the server kills a worker after 30 s.
TIMEOUT = 8
MAX_PAGE_SIZE = 10 * 1024 * 1024


logger = logging.getLogger(__name__)


class CatalogueError(Exception):
    """The catalogue could not be read; the message is shown to the instructor."""


@dataclass
class Syllabus:
    code: str = ""
    title: str = ""
    ects: str = ""
    english: bool = False  # the page's language: the app's course names are English
    los: list = field(default_factory=list)  # LO texts, in order: LO1, LO2, ...
    pos: list = field(default_factory=list)  # PO numbers in the table's columns, e.g. [1, 2, ..., 11]
    levels: dict = field(default_factory=dict)  # (LO index, PO number) -> 1..5
    problems: list = field(default_factory=list)  # cells and rows that could not be read, for the instructor


class _Tables(HTMLParser):
    """Collects every table with an id: rows of cells, each with its text and title attribute."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._stack, self._cell = {}, [], None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            table = {"rows": []}
            self._stack.append(table)
            if attrs.get("id"):
                self.tables[attrs["id"]] = table
        elif self._stack and tag == "tr":
            self._stack[-1]["rows"].append([])
        elif self._stack and tag in ("td", "th"):
            self._cell = {"text": "", "title": ""}
        elif self._cell is not None and attrs.get("title") and not self._cell["title"]:
            self._cell["title"] = attrs["title"]

    def handle_endtag(self, tag):
        if tag == "table" and self._stack:
            self._stack.pop()
        elif tag in ("td", "th") and self._cell is not None and self._stack and self._stack[-1]["rows"]:
            self._cell["text"] = re.sub(r"\s+", " ", self._cell["text"]).strip()
            self._stack[-1]["rows"][-1].append(self._cell)
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["text"] += data


def parse_course_page(html):
    """Read one course page. Problems are listed, never guessed: a cell that is not 1 to 5 stays empty."""
    tables = _Tables()
    tables.feed(html)
    found = tables.tables
    syllabus = Syllabus()

    info = found.get("grdDers")
    if info and len(info["rows"]) >= 2:
        header = [cell["text"] for cell in info["rows"][0]]
        values = [cell["text"] for cell in info["rows"][1]]
        syllabus.english = any("Course" in column for column in header)
        if len(header) >= 4 and len(values) >= len(header):
            syllabus.code = values[1]
            syllabus.title = values[2]
            syllabus.ects = values[-2] if len(values) >= 6 else ""

    outcomes = found.get("grdOgrenmeCiktilari")
    if outcomes is None:
        raise CatalogueError(_("This page has no learning outcomes table. Is it a course page of the Bologna catalogue?"))
    numbered = []
    for row in outcomes["rows"][1:]:
        if len(row) > 1 and row[1]["text"]:
            number = re.search(r"\d+", row[0]["text"])
            numbered.append((int(number.group()) if number else len(numbered) + 1, row[1]["text"]))
    syllabus.los = [text for _number, text in numbered]
    # The LO-PO rows are matched by their number (Ö3 is the LO numbered 3), not by position.
    index_of = {number: index for index, (number, _text) in enumerate(numbered)}
    if not syllabus.los:
        syllabus.problems.append(_("The catalogue lists no learning outcomes for this course."))

    matrix = found.get("grdProgCiktiKatki")
    if matrix is None or not matrix["rows"]:
        syllabus.problems.append(_("The catalogue has no LO-PO table for this course."))
        return syllabus

    columns = []
    for cell in matrix["rows"][0][1:]:
        number = re.fullmatch(r"[A-Za-zÇçPp]*\s*0*(\d+)", cell["text"])
        columns.append(int(number.group(1)) if number else None)
    syllabus.pos = [n for n in columns if n is not None]
    if not syllabus.pos:
        syllabus.problems.append(_("The LO-PO table has no PO numbers in its header, so its levels could not be read."))
    for number in sorted({n for n in syllabus.pos if syllabus.pos.count(n) > 1}):
        syllabus.problems.append(_("P%(n)s appears twice in the LO-PO table; the later column is used.") % {"n": number})

    whole_course = {}
    lo_rows = []
    for row in matrix["rows"][1:]:
        if not row:
            continue
        label = row[0]["text"]
        if label.lower() in ALL_ROW:
            target = whole_course
        elif re.fullmatch(r"[^\d\s]{0,3}\s*0*\d+", label):
            target = {}
            lo_rows.append((label, int(re.search(r"\d+", label).group()), target))
        else:
            continue
        for po, cell in zip(columns, row[1:]):
            raw = cell["text"]
            if po is None or raw in ("", "-"):
                continue
            if raw.isdigit() and int(raw) in LEVELS:
                target[po] = int(raw)
            else:
                syllabus.problems.append(
                    _("%(row)s, P%(po)s: \"%(raw)s\" is not a level from 1 to 5, left empty.")
                    % {"row": label, "po": po, "raw": raw}
                )

    unmatched = [label for label, number, _levels in lo_rows if number not in index_of]
    if unmatched:
        syllabus.problems.append(
            _("The LO-PO table has rows for learning outcomes the course does not list (%(rows)s); they are left out.")
            % {"rows": ", ".join(unmatched)}
        )
    for _label, number, levels in lo_rows:
        if number in index_of:
            for po, level in levels.items():
                syllabus.levels[(index_of[number], po)] = level

    if not syllabus.levels and whole_course and syllabus.los:
        # Only the course as a whole is graded: the same levels for every LO.
        for index in range(len(syllabus.los)):
            for po, level in whole_course.items():
                syllabus.levels[(index, po)] = level
        syllabus.problems.append(
            _("The catalogue gives the levels for the whole course only, so every LO starts with the same levels. Adjust them per LO.")
        )
    elif not syllabus.levels and syllabus.los:
        syllabus.problems.append(_("The LO-PO table in the catalogue is empty. Enter the levels below."))
    elif syllabus.levels and len({tuple(sorted(levels.items())) for _label, _n, levels in lo_rows}) == 1 and len(lo_rows) > 1:
        syllabus.problems.append(
            _("Every LO has the same row in the catalogue, which is usually copied, not measured. Check the levels.")
        )
    return syllabus


def _get(url):
    request = urllib.request.Request(url, headers={"User-Agent": "aculator (course catalogue import)"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read(MAX_PAGE_SIZE + 1)
            charset = response.headers.get_content_charset()
    except (OSError, http.client.HTTPException) as error:
        logger.warning("Bologna catalogue: %s: %s", url, error)
        raise CatalogueError(_("The course catalogue did not answer. Try again later.")) from error
    return decode_page(body[:MAX_PAGE_SIZE], charset)


def decode_page(body, charset=None):
    """Bytes of a catalogue page as text: the declared charset, else UTF-8, else Windows-1254 (Turkish)."""
    if charset is None:
        declared = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", body[:4096], re.IGNORECASE)
        charset = declared.group(1).decode("ascii") if declared else None
    for candidate in (charset, "utf-8"):
        if not candidate:
            continue
        try:
            return body.decode(candidate)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("cp1254", errors="replace")


def _course_ids(lang):
    """{course code without spaces: catalogue id} for the configured program, cached for a day."""
    key = f"bologna-course-ids:{settings.BOLOGNA_URL}:{settings.BOLOGNA_PROGRAM}"
    ids = cache.get(key)
    if not ids:
        page = _get(f"{settings.BOLOGNA_URL}progCourses.aspx?lang={lang}&curSunit={settings.BOLOGNA_PROGRAM}")
        ids = {}
        for match in re.finditer(
            r'prolizOpenCourseDetails\((\d+)\);" id="grdBolognaDersler_btnDersKod_\d+"[^>]*>(?:<font[^>]*>)?([^<]+)<', page
        ):
            ids.setdefault(match.group(2).replace(" ", "").upper(), match.group(1))
        if not ids:
            # A maintenance page or a changed layout: say so, and do not remember it for a day.
            raise CatalogueError(_("The course catalogue did not list any course. Try again later."))
        cache.set(key, ids, 24 * 60 * 60)
    return ids


def fetch_course(code, lang="en"):
    """The catalogue page of a course code such as CSE201, read and parsed."""
    lang = "tr" if lang.startswith("tr") else "en"
    course_id = _course_ids(lang).get(code.replace(" ", "").upper())
    if course_id is None:
        raise CatalogueError(_("%(code)s is not in the course catalogue of this program.") % {"code": code})
    query = urllib.parse.urlencode({"curCourse": course_id, "lang": lang})
    return parse_course_page(_get(f"{settings.BOLOGNA_URL}progCourseDetails.aspx?{query}"))
