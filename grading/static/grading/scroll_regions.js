// A table wider than the screen scrolls sideways. Give it a name and a tab
// stop so a keyboard can scroll it too; a table that fits gets neither, so it
// adds no extra stop on a desktop (#45).
(() => {
  const wraps = document.querySelectorAll(".table-wrap[data-label]");
  const update = (wrap) => {
    if (wrap.scrollWidth > wrap.clientWidth) {
      wrap.setAttribute("role", "region");
      wrap.setAttribute("aria-labelledby", wrap.dataset.label);
      wrap.tabIndex = 0;
    } else {
      wrap.removeAttribute("role");
      wrap.removeAttribute("aria-labelledby");
      wrap.removeAttribute("tabindex");
    }
  };
  // Widths change after load too: the web font arrives, the screen turns.
  const observer = new ResizeObserver((entries) =>
    entries.forEach((entry) => update(entry.target.closest(".table-wrap"))),
  );
  wraps.forEach((wrap) => {
    update(wrap);
    observer.observe(wrap);
    if (wrap.firstElementChild) observer.observe(wrap.firstElementChild);
  });
})();
