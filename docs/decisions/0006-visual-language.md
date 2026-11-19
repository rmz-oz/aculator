# 6. Visual language and chart libraries

Interactive charts in the app use Apache ECharts 6 (Apache 2.0). Printed and PDF figures use Observable Plot, with
d3-hierarchy or d3-sankey when a layout is needed. Charts are never positioned by hand: the library does layout,
tooltips and keyboard access, we only pass data, colors and type.

Highcharts was the other candidate. It has the best accessibility module, but it is free only for coursework; if the
department ever runs aculator for real it needs a commercial license.

Look:

- White background. Black (#0D1117) for text and marks, blue (#1D4ED8) for the measured value or the selected path,
  red (#C21F32) only for below target. No other colors, no gradients, no colored stripes on cards.
- On the profile a PO score is blue when the target is met and it is at or above the department mean, black when the
  target is met but it is below the mean (a comparison, not a failure), red when a component is below the target.
  The target is `settings.PO_TARGET`, 70 by default; a PO is met when every component reaches it (MÜDEK 3.3).
- One typeface, Schibsted Grotesk. No Inter or Roboto. Proportional figures everywhere: its tabular set gives the
  decimal point a full figure width. Pages share `grading/static/grading/aculator.css` and `templates/base.html`.
- No rules, cards or boxed buttons. Space, weight and size separate things; actions are bold blue text.
- Every chart has a table view and a one line text summary for screen readers.
- Missing or thin evidence is its own state, never a confident number: no evidence is hatched, a single assessment
  is the grey words "1 grade" (#42). Thin scores stay out of the class average and get no colour.

Explaining a score: a ring (ECharts sunburst, courses inside, assessments outside, the rest of 100 empty) next to each
PO on the profile, and a detail page per PO with a slopegraph (Observable Plot) from grades to LOs to the PO, line
width is the weight, plus the same numbers as a table (#41). The contributions come from `grading/explain.py` and add
up to the score exactly. The libraries are vendored in `grading/static/vendor/` with the version in the file name.

Status: proposed, team to confirm.
