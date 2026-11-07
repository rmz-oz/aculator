"""Builds docs/slides/checkpoint1.html, one self-contained file (fonts and diagrams inlined).

    python3 docs/slides/build.py

Sources in docs/slides/src: arch.svg and classes.svg are copies of the generated diagrams, er.d2 is
rendered to er.svg with d2. Keys in the deck: arrows or space, O overview, N notes, F full screen.
"""

import base64
import json
import math
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "src"

INK, MUTED, LINE, BLUE, RED = "#0D1117", "#4A5160", "#D5D9E0", "#1D4ED8", "#C21F32"


def b64(name):
    return base64.b64encode((SRC / name).read_bytes()).decode()


# d2's sql_table colors come from its theme; recolor them to the deck's ink and grey.
RECOLOR = {"#0D32B2": INK, "#4A6FF3": "#8A909C", "#676C7E": MUTED}


def svg_img(name, style):
    data = (SRC / name).read_text()
    if name == "er.svg":
        for a, b in RECOLOR.items():
            data = data.replace(a, b)
    enc = base64.b64encode(data.encode()).decode()
    return f'<img src="data:image/svg+xml;base64,{enc}" style="{style}" alt="">'


# ---------------------------------------------------------------- charts (Elif example)
# Shares follow from the guideline numbers: LO1 = .6 midterm + .4 project = 86.0,
# LO2 = 2/7 midterm + 5/7 project = 82.857, PO1 = 2/3 LO1 + 1/3 LO2 = 84.952.

def slope_svg():
    W, H = 1040, 640
    xs = (130, 470, 760)
    lo, hi = 78, 92

    def y(v):
        return 60 + (hi - v) / (hi - lo) * (H - 120)

    nodes = {"mid": (xs[0], 90, "Midterm", "90"), "proj": (xs[0], 80, "Project", "80"),
             "lo1": (xs[1], 86.0, "LO 1", "86.0"), "lo2": (xs[1], 82.857, "LO 2", "82.9"),
             "po1": (xs[2], 84.952, "PO 1", "85.0")}
    edges = [("mid", "lo1", .6, 2), ("proj", "lo1", .4, 2), ("mid", "lo2", 2 / 7, 2), ("proj", "lo2", 5 / 7, 2),
             ("lo1", "po1", 2 / 3, 3), ("lo2", "po1", 1 / 3, 3)]
    out = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="Schibsted Grotesk">']
    for a, b, share, step in edges:
        (x1, v1, *_), (x2, v2, *_) = nodes[a], nodes[b]
        out.append(f'<line data-step="{step}" x1="{x1}" y1="{y(v1):.1f}" x2="{x2}" y2="{y(v2):.1f}" '
                   f'stroke="{INK}" stroke-opacity=".85" stroke-width="{2 + share * 22:.1f}" stroke-linecap="round"/>')
    for key, (x, v, label, val) in nodes.items():
        step = 1 if x == xs[0] else 2 if x == xs[1] else 3
        color = BLUE if key == "po1" else INK
        r = 14 if key == "po1" else 10
        anchor, dx = ("end", -28) if x == xs[0] else ("start", 28)
        out.append(f'<g data-step="{step}"><circle cx="{x}" cy="{y(v):.1f}" r="{r}" fill="{color}"/>'
                   f'<text x="{x + dx}" y="{y(v) - 6:.1f}" text-anchor="{anchor}" font-size="26" fill="{MUTED}" stroke="#fff" stroke-width="8" paint-order="stroke">{label}</text>'
                   f'<text x="{x + dx}" y="{y(v) + 32:.1f}" text-anchor="{anchor}" font-size="40" font-weight="800" '
                   f'fill="{color}" stroke="#fff" stroke-width="8" paint-order="stroke">{val}</text></g>')
    # the brief's 84: LO2 cut to 82 first
    out.append(f'<g data-step="4"><line x1="{xs[2] - 60}" y1="{y(84):.1f}" x2="{xs[2] + 20}" y2="{y(84):.1f}" '
               f'stroke="{RED}" stroke-width="4" stroke-dasharray="8 8"/>'
               f'<text x="{xs[2] + 28}" y="{y(84) + 64:.1f}" font-size="30" font-weight="700" fill="{RED}">84 in the brief</text></g>')
    out.append("</svg>")
    return "".join(out)


def arc(cx, cy, r0, r1, a0, a1):
    def pt(r, a):
        return cx + r * math.sin(a), cy - r * math.cos(a)
    large = 1 if a1 - a0 > math.pi else 0
    p = [pt(r1, a0), pt(r1, a1), pt(r0, a1), pt(r0, a0)]
    return (f"M{p[0][0]:.1f},{p[0][1]:.1f} A{r1},{r1} 0 {large} 1 {p[1][0]:.1f},{p[1][1]:.1f} "
            f"L{p[2][0]:.1f},{p[2][1]:.1f} A{r0},{r0} 0 {large} 0 {p[3][0]:.1f},{p[3][1]:.1f} Z")


def ring_svg():
    S = 720
    c = S / 2
    full = 2 * math.pi / 100  # radians per point, the ring is out of 100
    lo1, lo2 = 86.0 * 2 / 3, 82.857142857 / 3
    outer = [(.6 * 90 * 2 / 3, BLUE), (.4 * 80 * 2 / 3, INK), (2 / 7 * 90 / 3, BLUE), (5 / 7 * 80 / 3, INK)]
    gap = 0.012
    out = [f'<svg viewBox="0 0 {S} {S}" width="{S}" height="{S}" font-family="Schibsted Grotesk">',
           f'<circle cx="{c}" cy="{c}" r="{(250 + 330) / 2}" fill="none" stroke="#EEF0F3" stroke-width="80"/>',
           f'<circle cx="{c}" cy="{c}" r="{(160 + 240) / 2}" fill="none" stroke="#EEF0F3" stroke-width="80"/>']
    a = 0
    for v, label in ((lo1, "LO 1"), (lo2, "LO 2")):
        out.append(f'<path data-step="1" d="{arc(c, c, 160, 240, a + gap, a + v * full - gap)}" fill="{MUTED}"/>')
        mid = a + v * full / 2
        out.append(f'<text data-step="1" x="{c + 200 * math.sin(mid):.1f}" y="{c - 200 * math.cos(mid) + 9:.1f}" '
                   f'text-anchor="middle" font-size="26" font-weight="700" fill="#fff">{label}</text>')
        a += v * full
    a = 0
    for v, col in outer:
        out.append(f'<path data-step="2" d="{arc(c, c, 250, 330, a + gap, a + v * full - gap)}" fill="{col}"/>')
        a += v * full
    out.append(f'<text x="{c}" y="{c - 14}" text-anchor="middle" font-size="30" fill="{MUTED}">PO 1</text>'
               f'<text x="{c}" y="{c + 50}" text-anchor="middle" font-size="76" font-weight="800" fill="{BLUE}">85.0</text>')
    out.append("</svg>")
    return "".join(out)


def bars_svg():
    W = 1500
    rows = [("400 students", 9600, "1.4 MB", "1.6 s", 1), ("4,000 students", 96000, "13 MB", "9.6 s", 2)]
    out = [f'<svg viewBox="0 0 {W} 330" width="{W}" height="330" font-family="Schibsted Grotesk">']
    for i, (label, n, mb, t, step) in enumerate(rows):
        y = 30 + i * 150
        w = max(8, n / 96000 * 760)
        out.append(f'<g data-step="{step}"><text x="0" y="{y + 52}" font-size="34" fill="{MUTED}">{label}</text>'
                   f'<rect x="300" y="{y}" width="{w:.0f}" height="80" fill="{BLUE}"/>'
                   f'<text x="{300 + w + 24:.0f}" y="{y + 40}" font-size="40" font-weight="800" fill="{INK}">{n:,} grades</text>'
                   f'<text x="{300 + w + 24:.0f}" y="{y + 76}" font-size="28" fill="{MUTED}">{mb} on disk, generated in {t}</text></g>')
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- frames
def h2(t):
    return f'<h2>{t}</h2>'


def p(t, cls="", step=None):
    s = f' data-step="{step}"' if step else ""
    return f'<p class="{cls}"{s}>{t}</p>'


FRAMES = {}


def frame(fid, x, y, s, r, html, cls=""):
    FRAMES[fid] = {"x": x, "y": y, "s": s, "r": r, "html": html, "cls": cls}


frame("cover", 0, 0, 1.0, 0, '''
<div class="cover">
  <p class="kicker">CSE 321 Data Systems, Checkpoint 1, 12 November 2026</p>
  <h1>aculator turns grades into program outcome scores</h1>
  <div class="cover-foot">
    <p>Django Unchained<br><span class="muted">Yaren Sargın, Esin Sarıaltın, Rana İlgi Yılmaz, Ramiz Özdemir</span></p>
    <p class="muted right">github.com/rmz-oz/aculator</p>
  </div>
</div>''')

frame("elif", 2300, -150, 1.0, -3, f'''
{h2("Elif’s PO 1 is 85.0, not 84")}
<div class="row">
  <div class="col narrow">
    {p("Grades feed learning outcomes, outcomes feed the program outcome. Every step is a weighted average; line width is the weight.", "", 1)}
    {p("Nothing is rounded until it is shown.", "strong", 3)}
    {p("The brief cuts LO 2 to 82 before using it and gets 84. Both numbers are unit tests.", "", 4)}
  </div>
  <div class="col">{slope_svg()}</div>
</div>''')

frame("ring", 2350, 1080, 0.55, 4, f'''
{h2("85.0 = 44.6 from the midterm + 40.4 from the project")}
<div class="row">
  <div class="col">{ring_svg()}</div>
  <div class="col narrow">
    {p("A weighted average is linear, so every score splits exactly into what each assessment gave it.", "", 1)}
    {p('<span class="blue">Blue</span> is the midterm, black the project. The parts always add up to the score, and a test checks it.', "", 2)}
  </div>
</div>''')

frame("arch", 4800, 0, 1.0, 0, f'''
{h2("One Django app, one database, one deploy")}
<div class="fig">{svg_img("arch.svg", "width:1680px;height:420px;object-fit:contain")}</div>
<div class="three">
  <div data-step="1"><h3>Server rendered</h3><p>Django templates with HTMX. One language, one repository, no separate front end.</p></div>
  <div data-step="2"><h3>Work off the request</h3><p>Bulk imports, view refreshes and email run in a worker fed by a Redis queue.</p></div>
  <div data-step="3"><h3>Every green main ships</h3><p>Tests, a Docker image on GHCR and a deploy to Render in Frankfurt.</p></div>
</div>''')

frame("deploy", 6060, -380, 0.28, 0, f'''
{h2("A merge is live in about four minutes")}
<div class="pipe">
  <div><b>Pull request</b><span>one teammate approves</span></div>
  <div><b>CI</b><span>ruff, migrations check, tests on PostgreSQL 16; zero tests fails</span></div>
  <div><b>Image</b><span>ghcr.io/rmz-oz/aculator, tagged with the commit</span></div>
  <div><b>Render</b><span>deploy hook, migrate, then the app starts</span></div>
  <div class="blue-b"><b>/healthz/</b><span>returns the commit; the workflow waits until it is the new one</span></div>
</div>
{p("Live at aculator.onrender.com. The free database expires on 3 December, so backups come first (#32).", "muted")}''', "detail")

frame("classes", 4900, 1360, 1.0, 3, f'''
{h2("Learning outcomes belong to the term, not the course")}
<div class="fig">{svg_img("classes.svg", "width:1680px;height:540px;object-fit:contain")}</div>
{p("A course can change its outcomes between terms and a student can retake it, so outcomes, assessments and enrollments hang off <b>CourseOffering</b>. Generated from the models; a test fails if the diagram drifts.", "", None)}''')

frame("er", 4800, 2920, 1.15, 0, f'''
{h2("Grades are stored once, everything else is derived")}
<div class="row">
  <div class="col">{svg_img("er.svg", "width:1180px;height:760px;object-fit:contain")}</div>
  <div class="col narrow">
    {p('<b class="blue">Grade</b> is the only table a score is written to.', "", 1)}
    {p("Learning outcome scores, course PO scores and the student profile are computed from it.", "", 2)}
    {p("Drawn from the models, like the class diagram.", "muted", 2)}
  </div>
</div>''')

frame("views", 6200, 2420, 0.3, 0, f'''
{h2("Three materialized views do the reading")}
<table class="t">
<tr><th>View</th><th>One row per</th><th>Used by</th></tr>
<tr><td>mv_student_lo</td><td>student, learning outcome</td><td>course report</td></tr>
<tr><td>mv_course_po</td><td>student, offering, PO</td><td>instructor page</td></tr>
<tr><td>mv_student_po</td><td>student, PO, credit weighted</td><td>student profile</td></tr>
</table>
{p("REFRESH CONCURRENTLY after grades change, so reads never wait. The SQL ran on PostgreSQL 16 with the Elif data on 29 October; the Django version is #9 in Sprint 2.", "muted")}''', "detail")

frame("schema", 2500, 2760, 0.8, -4, f'''
{h2("3NF where we write, snowflake where we read")}
<div class="two">
  <div data-step="1"><h3>Write side</h3>
    <p>Normalized tables for grade entry.</p><p>Unique keys stop double grades.</p>
    <p>Scores are NUMERIC, never FLOAT.</p><p>A course or term with data cannot be deleted.</p></div>
  <div data-step="2"><h3 class="blue">Read side</h3>
    <p>Fact table: Grade, one row per student and assessment.</p>
    <p>Dimensions: student, assessment, offering, term, course.</p>
    <p>The weights are bridges between dimensions, so it is a snowflake, not a star.</p></div>
</div>''')

frame("size", 2600, 3820, 0.7, 3, f'''
{h2("96,000 grades fit in 13 MB")}
<div class="fig left">{bars_svg()}</div>
{p("Measured on PostgreSQL 16 with the fake data command, fixed seed: 8 terms, 64 offerings, 11 POs. Size grows linearly; ten years of a real department, about 240,000 grades, is around 33 MB.", "", 3)}''')

TABLES = [("grading_grade", "9,600", "1,360 kB"), ("grading_enrollment", "2,400", "416 kB"),
          ("grading_assessmentloweight", "384", "128 kB"), ("grading_lopoweight", "375", "128 kB"),
          ("grading_learningoutcome", "192", "96 kB"), ("grading_assessment", "256", "88 kB"),
          ("grading_courseoffering", "64", "72 kB")]
frame("tables", 1480, 4120, 0.3, 0, f'''
{h2("Every table, 400 students")}
<table class="t">
<tr><th>Table</th><th class="r">Rows</th><th class="r">With indexes</th></tr>
{"".join(f"<tr><td>{a}</td><td class='r'>{b}</td><td class='r'>{c}</td></tr>" for a, b, c in TABLES)}
</table>
{p("pg_total_relation_size, measured 7 November.", "muted")}''', "detail")

frame("roles", 0, 2900, 1.0, 0, f'''
{h2("Each role sees exactly its part")}
<div class="three roles">
  <div data-step="1"><h3>Student</h3><p>Their own grades and profile. Never another name.</p></div>
  <div data-step="2"><h3>Instructor</h3><p>The offerings they teach, set per term, with every grade in them.</p></div>
  <div data-step="3"><h3 class="blue">Head of department</h3><p>Everything in the department, and which POs fall under target.</p></div>
</div>
{p("One file decides it, grading/access.py, and every page asks it.", "muted", 3)}''')

ACCESS = """def visible_grades(user):
    role = role_of(user)
    qs = Grade.objects.all()
    if role == HEAD:
        return qs
    if role == INSTRUCTOR:
        return qs.filter(enrollment__offering__instructors=user)
    if role == STUDENT:
        return qs.filter(enrollment__student=user)
    return qs.none()"""
frame("access", 1250, 3290, 0.28, 0, f'''
{h2("Three groups, one rule file, nine tests")}
<pre>{ACCESS}</pre>
{p("No role, inactive or anonymous: nothing. Pull request #68.", "muted")}''', "detail")

frame("next", 0, 4020, 0.7, -3, f'''
{h2("Next: measure what we designed")}
<table class="t big">
<tr><th>Work</th><th>Report section</th><th class="r">Sprint</th></tr>
<tr><td>Materialized views and refresh</td><td>Scalability</td><td class="r">2</td></tr>
<tr><td>Table sizes with real course loads, indexes</td><td>Data model</td><td class="r">3</td></tr>
<tr><td>Bulk import in one transaction</td><td>Consistency</td><td class="r">3</td></tr>
<tr><td>Grades partitioned by term</td><td>Scalability</td><td class="r">4</td></tr>
<tr><td>Backups and a failure plan</td><td>Fault tolerance</td><td class="r">4</td></tr>
<tr><td>Load test with and without views</td><td>Scalability</td><td class="r">5</td></tr>
</table>''')

frame("end", 2470, 1960, 0.42, 0, '''
<div class="closing">
  <div class="name">aculator</div>
  <div class="quote"><span class="dot"></span><i>Every score can be explained.</i><p class="muted">github.com/rmz-oz/aculator</p></div>
</div>''')

# ---------------------------------------------------------------- the path
# (frame, step, zoom rect in frame px or None, speaker, note)
STOPS = [
    ("cover", 0, None, "Ramiz", "One sentence: a department enters grades once, and every student gets a profile against the eleven program outcomes."),
    ("elif", 1, None, "Esin", "Start with the two grades: midterm 90, project 80."),
    ("elif", 2, None, "Esin", "They feed two learning outcomes. Line width is the weight: LO 1 is 86.0, LO 2 is 82.857."),
    ("elif", 3, None, "Esin", "The outcomes feed PO 1: 85.0. Nothing was rounded on the way."),
    ("elif", 4, None, "Esin", "The brief rounds LO 2 to 82 first and gets 84. We keep the exact value; both numbers are unit tests."),
    ("ring", 2, None, "Esin", "Because it is linear, 85.0 splits exactly: 44.6 from the midterm, 40.4 from the project. This answers the instructor's question, where does this number come from."),
    ("arch", 0, None, "Ramiz", "One Django app on Render, one PostgreSQL database, a worker for anything slow."),
    ("arch", 0, (1150, 560, 1240), "Ramiz", "Follow the blue arrows: grades are written once into PostgreSQL, the worker refreshes the views. ALMS and mail are the only outside services."),
    ("arch", 3, None, "Ramiz", "Server rendered with HTMX, slow work off the request, every green main ships."),
    ("deploy", 0, None, "Ramiz", "If asked how deploys work: the health check returns the commit, so the workflow knows the new version is live."),
    ("classes", 0, None, "Ramiz", "The decision is CourseOffering: outcomes belong to a course in a given term. The diagram is generated from the models."),
    ("er", 1, None, "Yaren", "The ER diagram from the models. Grade, in blue, is the only table a score is written to."),
    ("er", 2, None, "Yaren", "Everything else is computed from it."),
    ("views", 0, None, "Yaren", "Three materialized views serve the pages. The SQL is tested; the Django version is this sprint's work."),
    ("schema", 2, None, "Yaren", "Answer the report question directly: normalized for writes, a snowflake for reads, and why not a star."),
    ("size", 2, None, "Yaren", "Measured, not estimated: ten times the students, ten times the rows and size."),
    ("size", 3, None, "Yaren", "Ten years of a real department is around 33 MB."),
    ("tables", 0, None, "Yaren", "Per table numbers, if asked."),
    ("roles", 3, None, "Rana", "Student, instructor, head of department. Each sees exactly its part; one file decides it."),
    ("access", 0, None, "Rana", "If asked: this is the actual rule for grades, with nine tests."),
    ("next", 0, None, "Rana", "Close with the plan and the demo date, 29 December."),
    ("end", 0, None, "Ramiz", "Thank you. Questions."),
]

ZONES = [("The number", -960, -1000), ("The system", 3840, -1000), ("The data", 3700, 3660), ("The team", -960, 4560)]


def build():
    fonts = "".join(
        f"@font-face{{font-family:'Schibsted Grotesk';font-style:{st};font-weight:400 900;"
        f"src:url(data:font/woff2;base64,{b64(f)}) format('woff2');unicode-range:{ur}}}"
        for f, st, ur in (("sg-latin.woff2", "normal", "U+0000-00FF,U+2000-206F,U+20AC"),
                          ("sg-latin-ext.woff2", "normal", "U+0100-02BA,U+1E00-1EFF"),
                          ("sg-italic.woff2", "italic", "U+0000-00FF,U+2000-206F")))
    frames = "".join(
        f'<section class="frame {f["cls"]}" id="f-{fid}" data-id="{fid}" style="left:{f["x"] - 960}px;top:{f["y"] - 540}px;'
        f'transform:rotate({f["r"]}deg) scale({f["s"]})">{f["html"]}</section>'
        for fid, f in FRAMES.items())
    zones = "".join(f'<div class="zone" style="left:{x}px;top:{y}px">{t}</div>' for t, x, y in ZONES)
    pts = " ".join(f'{FRAMES[f]["x"]},{FRAMES[f]["y"]}' for f in dict.fromkeys(s[0] for s in STOPS))
    path = (f'<svg class="path" style="left:-2000px;top:-2000px" width="10000" height="8000" viewBox="-2000 -2000 10000 8000">'
            f'<polyline points="{pts}" fill="none" stroke="{LINE}" stroke-width="6" stroke-dasharray="2 22" stroke-linecap="round"/></svg>')
    data = json.dumps({"frames": {k: {kk: v[kk] for kk in "xysr"} for k, v in FRAMES.items()},
                       "stops": [{"f": f, "step": st, "rect": rc, "who": who, "note": n} for f, st, rc, who, n in STOPS]})
    html = (HERE / "template.html").read_text()
    html = (html.replace("/*FONTS*/", fonts).replace("<!--WORLD-->", path + zones + frames)
            .replace("/*DATA*/", data))
    (HERE / "checkpoint1.html").write_text(html)
    print("checkpoint1.html", round(len(html) / 1024), "kB,", len(STOPS), "stops")


if __name__ == "__main__":
    build()
