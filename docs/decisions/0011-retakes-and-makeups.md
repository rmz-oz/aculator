# 11. Retakes and makeup exams

Acıbadem's undergraduate regulation (Resmî Gazete 20 September 2026, no. 33376):

- Article 29(2): "Tekrarlanan derste, önceki not ne olursa olsun alınan son not geçerlidir." Article 37 counts the
  last grade of a repeated course in the GPA.
- Article 32(9): "Bütünleme sınavında alınan not, yarıyıl/yıl sonu sınav notu yerine geçer." Students who failed the
  final, or missed it with an excuse, can take it.

Before this, a failed attempt and its retake both counted across courses with full ECTS: the failed 40 pulled the
passed 75 down and the course weighed twice. A makeup was averaged with the final it should replace.

## Retakes (#104)

A course taken more than once counts once across courses: its latest attempt that has scores. Terms are ordered by
year, then spring, summer, fall. An attempt without scores (a withdrawal, or a retake that is not graded yet) leaves
the earlier attempt in place, so enrolling again does not wipe a student's evidence for a term.

Each attempt keeps its own LO and PO scores in its course report, and the student profile lists both attempts with
the one that counts. The choice is made over all of the student's courses, not only the ones a viewer may see: an
instructor who taught only the failed attempt sees no cross-course score from it.

No stored flag: `refresh_scores()` (migration 0014) and `services.counting_enrollments` apply the same rule when they
compute, so nothing has to be kept in sync. A retake enrollment already refreshes its student's cross-course rows.

## Makeups (#105)

`Assessment.replaces` names the assessment a makeup replaces, in the same offering, one makeup per assessment and no
chains. For a student with a graded makeup, the replaced assessment is left out of every LO it feeds, even when the
makeup is lower, as the regulation says. The makeup feeds its own LOs with its own weights, so an LO that only the
final fed has no evidence left for that student.

A makeup the student is marked absent from is no attempt: it is left out and the final stays. The regulation does
not say this directly; it is the reading that does not turn an absence into a 0 averaged with the final.

The course report, the explanation and the score tables all leave out the same grades (test_retake_makeup).
