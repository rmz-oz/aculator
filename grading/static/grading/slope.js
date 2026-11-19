// Slopegraph on the PO detail page (#41, decision 0006): grades, LOs and the
// PO as three columns, line width is the weight that flows along each link.
(() => {
  const host = document.getElementById("slope");
  const source = document.getElementById("slope-data");
  if (!host || !source || !window.Plot) return;
  const { points, links, po } = JSON.parse(source.textContent);
  const columns = ["Grades", "Learning outcomes", po];
  const at = new Map(points.map((p) => [p.name, p]));
  const segments = links
    .filter((l) => at.has(l.from) && at.has(l.to))
    .map((l) => ({ ...l, a: at.get(l.from), b: at.get(l.to) }));
  const maxWeight = Math.max(...segments.map((s) => s.weight));
  // Not zero based: a slopegraph compares positions, and grades bunched
  // between 80 and 90 would otherwise sit in a thin strip at the top.
  const scores = points.map((p) => p.score);
  const low = Math.max(0, Math.floor((Math.min(...scores) - 4) / 5) * 5);
  const high = Math.min(100, Math.ceil((Math.max(...scores) + 4) / 5) * 5);

  const height = Math.max(260, Math.min(520, (high - low) * 9 + 60));
  // Labels at least one line apart; the dots stay at their real height.
  const gap = ((high - low) / (height - 60)) * 16;

  const draw = () => {
    const width = Math.min(host.clientWidth || 900, 960);
    host.replaceChildren(Plot.plot({
      width,
      height,
      marginLeft: 150,
      marginRight: 150,
      marginTop: 30,
      style: { fontFamily: "Schibsted Grotesk, system-ui, sans-serif", fontSize: "13px", color: "#0D1117" },
      x: { domain: columns, axis: "top", label: null, tickSize: 0, padding: 0 },
      y: { domain: [low, high], axis: null },
      marks: [
        Plot.link(segments, {
          x1: (d) => d.a.column, y1: (d) => d.a.score,
          x2: (d) => d.b.column, y2: (d) => d.b.score,
          stroke: "#1D4ED8",
          strokeOpacity: 0.45,
          strokeWidth: (d) => 1 + 9 * (d.weight / maxWeight),
          title: (d) => `${d.from} to ${d.to}: ${(d.weight * 100).toFixed(1)} % of ${po}`,
        }),
        Plot.dot(points, {
          x: "column", y: "score", r: 4,
          fill: (d) => (d.column === po ? "#1D4ED8" : "#0D1117"),
          title: (d) => `${d.name}: ${d.score.toFixed(1)}`,
        }),
        Plot.text(spread(points.filter((d) => d.column === "Grades"), gap), {
          x: "column", y: "labelY", text: (d) => `${d.name} ${d.score.toFixed(1)}`,
          textAnchor: "end", dx: -10,
        }),
        Plot.text(spread(points.filter((d) => d.column === "Learning outcomes"), gap), {
          x: "column", y: "labelY", text: (d) => `${d.name} ${d.score.toFixed(1)}`,
          textAnchor: "middle", dy: -14, fill: "#5F646C", stroke: "#FFFFFF", strokeWidth: 4,
        }),
        Plot.text(points.filter((d) => d.column === po), {
          x: "column", y: "score", text: (d) => d.score.toFixed(1),
          textAnchor: "start", dx: 10, fontSize: 18, fontWeight: 700, fill: "#1D4ED8",
        }),
      ],
    }));
  };
  draw();
  let timer;
  window.addEventListener("resize", () => { clearTimeout(timer); timer = setTimeout(draw, 150); });
})();

function spread(items, gap) {
  const sorted = [...items].sort((a, b) => b.score - a.score).map((d) => ({ ...d, labelY: d.score }));
  for (let i = 1; i < sorted.length; i += 1) {
    sorted[i].labelY = Math.min(sorted[i].labelY, sorted[i - 1].labelY - gap);
  }
  return sorted;
}
