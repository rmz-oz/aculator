# 12. Learning outcomes from the Bologna catalogue

#85 and #86 planned to read the LOs and the LO-PO table from the instructor's syllabus PDF. None of the four Fall 2026
CSE syllabi has an LO-PO table, and their layouts differ from course to course. The university's Bologna catalogue has
both for every course, in the same HTML layout: `progCourseDetails.aspx` on Proliz OIBS, with the LOs in
`grdOgrenmeCiktilari` and "Dersin Program Çıktılarına Katkısı" in `grdProgCiktiKatki` (rows Ö1, Ö2, ... or C1, C2, ...;
columns P1 to P11; levels 1 to 5; sometimes a "Tüm"/"All" row). About 70 Turkish universities run the same system.

So the source is the catalogue (`grading/bologna.py`), fetched by course code or from a page saved in the browser. A
PDF reader can come later for universities without it.

What is read:

- Only the three tables. The page also names the instructors; nothing else is kept (KVKK).
- A cell that is not 1 to 5 is left empty and listed. Nothing is guessed.
- Only a "Tüm" row: every LO starts with it, and the instructor is told to adjust per LO.
- An empty table, or the same row for every LO (usually copied, not measured), is said on the preview. On 28 Nov
  2026 most CSE courses of the catalogue had an empty table; CSE 220 and MAT 241 had filled ones.

Saving (#87): the preview is a form with every LO text and level, and nothing is written until the instructor saves it.
LOs are matched by code (LO1, LO2, ...): text and levels replaced, other LOs and every assessment weight kept. A preview
confirmed after the LOs changed elsewhere is refused. Only the offering's instructors can open it.

A level is given for a PO, but `LOPOWeight` points at a PO component. The level is written to every component of that
PO, so the model does not change.
