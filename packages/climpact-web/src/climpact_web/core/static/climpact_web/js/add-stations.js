/*
 * Add stations (#233, stations/add.html). Without JavaScript the page is one form: the
 * files go with "Add the files", the table with "Add N stations and check them" (or Enter,
 * which checks it again). Here:
 *
 * - a chosen or dropped file is sent at once (anywhere on the drop zone takes a drop);
 * - the table is checked as it is typed: what was typed is sent to the check address,
 *   kept there, and each row's Read column, its invalid cells, the line under the table
 *   and the button's count come back;
 * - a column pasted from a spreadsheet fills the cell pasted into and the cells under it,
 *   and two columns (latitude and longitude) the cells beside them too;
 * - Enter in a cell moves to the same cell of the next row, as in a spreadsheet.
 */
(function () {
  "use strict";

  var form = document.getElementById("add-form");
  if (!form) return;

  Array.prototype.forEach.call(document.querySelectorAll("[data-nojs]"), function (el) {
    el.hidden = true;
  });

  /* ---- Files: sent as soon as they are chosen or dropped ---- */
  var input = form.querySelector("[data-add-files]");
  var filesButton = form.querySelector('button[value="files"]');

  function sendFiles() {
    if (!input.files || !input.files.length) return;
    if (filesButton) form.requestSubmit(filesButton);
    else form.requestSubmit();
  }

  if (input) {
    input.addEventListener("change", sendFiles);
    var zone = document.querySelector("[data-add-drop]");
    if (zone) {
      ["dragenter", "dragover"].forEach(function (type) {
        zone.addEventListener(type, function (event) {
          event.preventDefault();
          zone.classList.add("is-over");
        });
      });
      ["dragleave", "dragend", "drop"].forEach(function (type) {
        zone.addEventListener(type, function () {
          zone.classList.remove("is-over");
        });
      });
      zone.addEventListener("drop", function (event) {
        event.preventDefault();
        if (!event.dataTransfer || !event.dataTransfer.files.length) return;
        input.files = event.dataTransfer.files;
        sendFiles();
      });
    }
  }

  /* ---- The table, checked as it is typed ---- */
  var checkUrl = form.getAttribute("data-check-url");
  var rows = Array.prototype.slice.call(form.querySelectorAll("[data-add-row]"));
  if (!checkUrl || !rows.length) return;

  var button = form.querySelector("[data-add-button]");
  var summary = form.querySelector("[data-add-summary]");
  var timer = null;
  var pending = null;

  function tableData() {
    var data = new FormData();
    var token = form.querySelector("input[name=csrfmiddlewaretoken]");
    if (token) data.append("csrfmiddlewaretoken", token.value);
    Array.prototype.forEach.call(
      form.querySelectorAll(".add-table input"),
      function (el) {
        data.append(el.name, el.value);
      }
    );
    return data;
  }

  function setInvalid(cell, message) {
    if (!cell) return;
    if (message) {
      cell.setAttribute("aria-invalid", "true");
      cell.classList.add("is-invalid");
    } else {
      cell.removeAttribute("aria-invalid");
      cell.classList.remove("is-invalid");
    }
  }

  function show(result) {
    var byFile = {};
    result.rows.forEach(function (r) {
      byFile[r.file] = r;
    });
    rows.forEach(function (row) {
      var r = byFile[row.getAttribute("data-add-row")];
      if (!r) return;
      row.setAttribute("data-state", r.state);
      row.classList.toggle("is-problem", r.state !== "ready");
      var status = row.querySelector("[data-status]");
      if (status) {
        status.textContent = r.status;
        status.className = "add-status add-status--" + r.status_kind;
      }
      setInvalid(row.querySelector('[data-cell="name"]'), r.name_error);
      setInvalid(row.querySelector('[data-cell="latitude"]'), r.latitude_error);
      setInvalid(row.querySelector('[data-cell="longitude"]'), r.longitude_error);
    });
    if (button) button.textContent = result.button;
    if (summary) summary.textContent = result.summary;
  }

  function check() {
    timer = null;
    if (pending) pending.abort();
    pending = new AbortController();
    fetch(checkUrl, {
      method: "POST",
      body: tableData(),
      credentials: "same-origin",
      headers: { "X-Requested-With": "fetch" },
      signal: pending.signal,
    })
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .then(function (result) {
        if (result) show(result);
      })
      .catch(function () {
        /* Offline or aborted: the form still checks everything when it is sent. */
      });
  }

  function later(delay) {
    if (timer) clearTimeout(timer);
    timer = setTimeout(check, delay);
  }

  var table = form.querySelector(".add-table");
  table.addEventListener("input", function () {
    later(500);
  });
  table.addEventListener("change", function () {
    later(0);
  });

  /* ---- Spreadsheet keys: Enter moves down; a pasted column fills down ---- */
  var COLUMNS = ["name", "latitude", "longitude"];

  function cellAt(rowIndex, column) {
    for (var i = rowIndex; i < rows.length; i++) {
      var cell = rows[i].querySelector('[data-cell="' + column + '"]');
      if (cell) return { cell: cell, row: i };
    }
    return null;
  }

  function position(cell) {
    var row = cell.closest("[data-add-row]");
    return { row: rows.indexOf(row), column: cell.getAttribute("data-cell") };
  }

  table.addEventListener("keydown", function (event) {
    var cell = event.target;
    if (event.key !== "Enter" || !cell.matches("[data-cell]")) return;
    event.preventDefault();
    var at = position(cell);
    var next = cellAt(at.row + 1, at.column);
    if (next) next.cell.focus();
    later(0);
  });

  table.addEventListener("paste", function (event) {
    var cell = event.target;
    if (!cell.matches("[data-cell]") || !event.clipboardData) return;
    var text = event.clipboardData.getData("text/plain").replace(/\r/g, "");
    if (text.indexOf("\n") === -1 && text.indexOf("\t") === -1) return;
    event.preventDefault();
    var lines = text.replace(/\n+$/, "").split("\n");
    var at = position(cell);
    var first = COLUMNS.indexOf(at.column);
    var rowIndex = at.row;
    lines.forEach(function (line) {
      var target = cellAt(rowIndex, at.column);
      if (!target) return;
      line.split("\t").forEach(function (value, offset) {
        var column = COLUMNS[first + offset];
        var into = column && target.row < rows.length
          ? rows[target.row].querySelector('[data-cell="' + column + '"]')
          : null;
        if (into) into.value = value.trim();
      });
      rowIndex = target.row + 1;
    });
    later(0);
  });
})();
