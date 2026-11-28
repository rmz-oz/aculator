(() => {
  const form = document.getElementById("paste-grades");
  if (!form) return;

  const grid = document.getElementById("grade-grid");
  const status = document.getElementById("paste-grades-status");
  // Same as the server renders "Current": the page language's decimal mark.
  const currentFormat = new Intl.NumberFormat(document.documentElement.lang, { maximumFractionDigits: 2 });
  const button = form.querySelector('button[type="submit"]');
  const csrfToken = form.querySelector('[name="csrfmiddlewaretoken"]').value;
  const roster = JSON.parse(document.getElementById("grade-grid-data").textContent);
  const students = JSON.parse(document.getElementById("grade-grid-students").textContent);
  // Translated per request (#49); "%(n)s" is filled in below, not a Python format.
  const t = JSON.parse(document.getElementById("grade-grid-strings").textContent);

  if (!window.Tabulator) {
    status.textContent = t.could_not_load;
    return;
  }

  const cellErrors = new Map();
  let anchor = null;
  let saving = false;

  const errorKey = (id, field) => `${id}:${field}`;

  const formatCell = (cell) => {
    const content = document.createElement("div");
    content.textContent = cell.getValue() ?? "";

    const message = cellErrors.get(
      errorKey(cell.getRow().getIndex(), cell.getField()),
    );
    if (message) {
      const error = document.createElement("span");
      error.className = "grade-paste-cell-error";
      error.textContent = message;
      content.append(error);
    }
    return content;
  };

  const column = (title, field) => ({
    title,
    field,
    editor: "input",
    editable: () => !saving,
    formatter: formatCell,
    variableHeight: true,
    headerSort: false,
    // Fixed widths so the name takes what is left and wraps between words.
    width: field === "student_number" ? 140 : 64,
    cellClick: (event, cell) => {
      anchor = cell;
      if (!(event.target instanceof HTMLInputElement)) grid.focus();
    },
    cellEdited: (cell) => {
      cellErrors.delete(errorKey(cell.getRow().getIndex(), cell.getField()));
      cell.getRow().reformat();
    },
  });

  // Read only, looked up from the student number in the same row.
  const lookup = (key) => ({
    title: key === "name" ? t.name : t.current,
    field: `_${key}`,
    headerSort: false,
    formatter: (cell) => students[cell.getRow().getData().student_number?.trim()]?.[key] ?? "",
  });

  const table = new Tabulator(grid, {
    data: roster,
    index: "id",
    layout: "fitColumns",
    editTriggerEvent: "dblclick",
    columns: [
      column(t.student_number, "student_number"),
      lookup("name"),
      lookup("current"),
      column(t.score, "score"),
    ],
  });

  table.on("tableBuilt", () => {
    button.disabled = roster.length === 0;
    // Tabulator's scroll wrapper sits between the grid and its rowgroup with
    // no role of its own, which role=grid does not allow (#45). A role of
    // presentation would normally take it out of the a11y tree, but ARIA
    // ignores that on a focusable element, so its tabindex has to go too;
    // every cell already has its own tabindex, so the grid stays keyboard
    // reachable without it.
    const holder = grid.querySelector(".tabulator-tableholder");
    holder?.setAttribute("role", "presentation");
    holder?.removeAttribute("tabindex");
    fitWidth();
    new ResizeObserver(fitWidth).observe(grid);
  });

  // On a narrow screen the current score is left out so the student number,
  // name and score keep room; it is only there to check against.
  // Only on a change: showing or hiding redraws the grid, which would wake
  // the ResizeObserver again and loop.
  let narrow = null;
  const fitWidth = () => {
    const now = grid.clientWidth < 440;
    if (now === narrow) return;
    narrow = now;
    if (narrow) table.hideColumn("_current");
    else table.showColumn("_current");
  };

  // Keyboard: the cell Tab lands on is where a paste starts, like a click,
  // and Enter opens it for editing like a double click (#45).
  grid.addEventListener("focusin", (event) => {
    const cellElement = event.target.closest?.(".tabulator-cell");
    const field = cellElement?.getAttribute("tabulator-field");
    if (field !== "student_number" && field !== "score") return;
    const row = table.getRows().find((r) => r.getElement().contains(cellElement));
    if (row) anchor = row.getCell(field);
  });
  grid.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || saving || !anchor) return;
    if (event.target instanceof HTMLInputElement) return;
    if (!anchor.getElement().contains(document.activeElement)) return;
    event.preventDefault();
    anchor.edit();
  });

  const redrawRows = () => table.getRows().forEach((row) => row.reformat());
  const withN = (template, n) => template.replace("%(n)s", n);

  grid.addEventListener("paste", async (event) => {
    if (saving || event.target instanceof HTMLInputElement) return;

    event.preventDefault();
    if (!anchor) {
      status.textContent = t.click_or_tab;
      return;
    }

    const text = event.clipboardData.getData("text/plain")
      .replace(/\r\n?/g, "\n")
      .replace(/\n$/, "");
    if (!text) return;

    const pasted = text.split("\n").map((line) => line.split("\t"));
    const width = anchor.getField() === "score" ? 1 : 2;

    if (pasted.some((cells) => cells.length !== width)) {
      status.textContent = width === 1 ? t.paste_one_column : t.paste_two_columns;
      return;
    }

    const rows = table.getRows();
    const start = rows.findIndex((row) => row.getIndex() === anchor.getRow().getIndex());
    if (start < 0 || start + pasted.length > rows.length) {
      status.textContent = t.does_not_fit;
      return;
    }

    const updates = pasted.map((cells, offset) => ({
      id: rows[start + offset].getIndex(),
      ...(width === 1
        ? {score: cells[0]}
        : {student_number: cells[0], score: cells[1]}),
    }));

    cellErrors.clear();
    await table.updateData(updates);
    redrawRows();
    // The redraw replaces the cells; find the start cell again and keep
    // keyboard focus on it, so Enter and the next paste still work there.
    const [id, field] = [anchor.getRow().getIndex(), anchor.getField()];
    // Two frames: Tabulator redraws the reformatted rows in the next one.
    requestAnimationFrame(() => requestAnimationFrame(() => {
      // Not table.getRow(id): the first row's id is 0, which it treats as "no row".
      anchor = table.getRows().find((row) => row.getIndex() === id).getCell(field);
      anchor.getElement().focus();
    }));
    status.textContent = withN(t.rows_pasted, updates.length);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (saving) return;

    saving = true;
    button.disabled = true;
    cellErrors.clear();
    redrawRows();
    status.textContent = t.saving;

    const data = table.getData();

    try {
      const response = await fetch(form.action, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify({
          rows: data.map(({student_number, score}) => ({student_number, score})),
        }),
      });
      const result = await response.json();

      if (response.ok) {
        for (const {student_number, score} of data) {
          const student = students[student_number.trim()];
          if (student && score.trim()) student.current = currentFormat.format(Number(score.trim().replace(",", ".")));
        }
        redrawRows();
        status.textContent = withN(
          result.saved_count === 1 ? t.grade_saved_one : t.grade_saved_other,
          result.saved_count,
        );
        return;
      }

      for (const {row, field, message} of result.errors ?? []) {
        cellErrors.set(errorKey(data[row].id, field), message);
      }
      redrawRows();
      status.textContent = result.message ?? t.nothing_saved;
    } catch {
      status.textContent = t.save_unconfirmed;
    } finally {
      saving = false;
      button.disabled = false;
    }
  });
})();
