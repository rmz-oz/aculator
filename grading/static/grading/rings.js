// Rings next to each PO on the student profile (#41, decision 0006).
// ECharts sunburst: courses inside, assessments outside, the rest of 100 left empty.
(() => {
  if (!window.echarts) return;
  const BLUE = "#1D4ED8";
  const EMPTY = "#EEF0F2";
  document.querySelectorAll("[data-ring]").forEach((el) => {
    const source = document.getElementById(el.dataset.ring);
    if (!source) return;
    const data = JSON.parse(source.textContent).map((node) => node.empty
      ? { ...node, itemStyle: { color: EMPTY }, emphasis: { disabled: true }, tooltip: { show: false } }
      : {
          ...node,
          itemStyle: { color: BLUE, opacity: 0.55 },
          children: node.children.map((child) => ({ ...child, itemStyle: { color: BLUE } })),
        });
    const chart = echarts.init(el, null, { renderer: "svg" });
    chart.setOption({
      animation: false,
      tooltip: {
        trigger: "item",
        confine: true,
        formatter: (p) => p.data.label || `${p.name}: ${p.value.toFixed(1)}`,
        textStyle: { fontFamily: "Schibsted Grotesk, system-ui, sans-serif", color: "#0D1117" },
        borderWidth: 0,
        extraCssText: "box-shadow: none; background: #FFFFFF;",
      },
      series: [{
        type: "sunburst",
        data,
        sort: null,
        radius: ["38%", "100%"],
        startAngle: 90,
        nodeClick: false,
        label: { show: false },
        itemStyle: { borderColor: "#FFFFFF", borderWidth: 1.5 },
        levels: [{}, { r0: "38%", r: "64%" }, { r0: "66%", r: "100%" }],
      }],
    });
    window.addEventListener("resize", () => chart.resize());
  });
})();
