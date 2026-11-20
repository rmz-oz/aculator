(() => {
  const form = document.getElementById("paste-grades");
  if (!form) return;

  const grid = document.getElementById("grade-grid");
  const status = document.getElementById("paste-grades-status");
  const button = form.querySelector('button[type="submit"]');
  const csrfToken = form.querySelector('[name="csrfmiddlewaretoken"]').value;
  const roster = JSON.parse(document.getElementById("grade-grid-data").textContent);
  const students = JSON.parse(document.getElementById("grade-grid-students").textContent);

  if (!window.Tabulator) {
    status.textContent = "The grade grid could not load.";
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
    title: key === "name" ? "Name" : "Current",
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
      column("Student number", "student_number"),
      lookup("name"),
      lookup("current"),
      column("Score", "score"),
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
  });

  const redrawRows = () => table.getRows().forEach((row) => row.reformat());

  grid.addEventListener("paste", async (event) => {
    if (saving || event.target instanceof HTMLInputElement) return;

    event.preventDefault();
    if (!anchor) {
      status.textContent = "Click the cell where the paste should start.";
      return;
    }

    const text = event.clipboardData.getData("text/plain")
      .replace(/\r\n?/g, "\n")
      .replace(/\n$/, "");
    if (!text) return;

    const pasted = text.split("\n").map((line) => line.split("\t"));
    const width = anchor.getField() === "score" ? 1 : 2;

    if (pasted.some((cells) => cells.length !== width)) {
      status.textContent = width === 1
        ? "Paste one score column into a score cell."
        : "Paste student numbers and scores into a student number cell.";
      return;
    }

    const rows = table.getRows();
    const start = rows.findIndex((row) => row.getIndex() === anchor.getRow().getIndex());
    if (start < 0 || start + pasted.length > rows.length) {
      status.textContent = "The pasted rows do not fit below the selected cell.";
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
    status.textContent = `${updates.length} rows pasted. Check the student numbers before saving.`;
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (saving) return;

    saving = true;
    button.disabled = true;
    cellErrors.clear();
    redrawRows();
    status.textContent = "Saving…";

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
          if (student && score.trim()) student.current = score.trim().replace(",", ".");
        }
        redrawRows();
        status.textContent = `${result.saved_count} grade${result.saved_count === 1 ? "" : "s"} saved.`;
        return;
      }

      for (const {row, field, message} of result.errors ?? []) {
        cellErrors.set(errorKey(data[row].id, field), message);
      }
      redrawRows();
      status.textContent = result.message
        ?? "Nothing was saved. Fix the highlighted cells and try again.";
    } catch {
      status.textContent = "The save could not be confirmed. Check the grades before retrying.";
    } finally {
      saving = false;
      button.disabled = false;
    }
  });
})();
