# 6. Visual language and chart libraries

Interactive charts in the app use Apache ECharts 6 (Apache 2.0). Printed and PDF figures use Observable Plot, with
d3-hierarchy or d3-sankey when a layout is needed. Charts are never positioned by hand: the library does layout,
tooltips and keyboard access, we only pass data, colors and type.

Highcharts was the other candidate. It has the best accessibility module, but it is free only for coursework; if the
department ever runs aculator for real it needs a commercial license.

Look:

- White background. Black (#0D1117) for text and marks, blue (#1D4ED8) for the measured value or the selected path,
  red (#C21F32) only for below target or "you". No other colors, no gradients, no colored stripes on cards.
- One typeface, Schibsted Grotesk. No Inter or Roboto. Tabular figures only in number columns, they widen commas in
  running text.
- Every chart has a table view and a one line text summary for screen readers.
- Missing or thin evidence is its own state (hatched or outlined), never a confident number.

Explaining a score: a ring (sunburst) next to each PO on the profile, a slopegraph from grades to LOs to the PO in the
detail view (#41). Mockups are linked in #41.

Status: proposed, team to confirm.
