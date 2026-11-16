/*
 * Step 2, Check quality (#77, #174): links the worklist (the "look wrong" rows and the
 * tables of the groups) and the daily charts under Details both ways. Needs charts.js
 * (window.ClimpactCharts) and htmx; without JavaScript the lists, tables, pagers (plain
 * links) and downloads work and the "Show on chart" buttons stay hidden.
 *
 * - List to chart: "Show on chart" ([data-qc-show], data-date, data-chart) opens Details
 *   and the chart's tab, moves the chart to the date (ClimpactCharts.focusDate), marks the
 *   row and moves focus to the chart.
 * - Chart to list: a click on a chart ("climpact:chartpick") marks the rows of that date
 *   in the lists and tables of the checks that flagged it, loading the page that holds it
 *   (stations:qc_table ?date=) when it is not shown, opens the groups that hold them and
 *   scrolls to the first.
 */
(function () {
  "use strict";

  var doc = document;
  var selected = null;
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function scrollTo(el) {
    el.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "center" });
  }

  function reveal(scope) {
    Array.prototype.forEach.call((scope || doc).querySelectorAll("[data-qc-js]"), function (el) {
      el.hidden = false;
    });
  }

  function openAround(el) {
    for (var d = el.closest("details"); d; d = d.parentElement.closest("details")) d.open = true;
  }

  function mark(date) {
    selected = date;
    Array.prototype.forEach.call(doc.querySelectorAll("[data-qc-table] tr[data-date], [data-qc-finding]"), function (tr) {
      var on = tr.getAttribute("data-date") === date;
      tr.classList.toggle("is-selected", on);
      if (on) tr.setAttribute("aria-current", "true");
      else tr.removeAttribute("aria-current");
    });
  }

  function openTab(panel) {
    var tab = panel && doc.getElementById(panel.id + "-tab");
    if (tab && tab.getAttribute("aria-selected") !== "true") tab.click();
  }

  doc.addEventListener("click", function (event) {
    var button = event.target.closest("[data-qc-show]");
    if (!button || !window.ClimpactCharts) return;
    var date = button.getAttribute("data-date");
    var figure = doc.getElementById(button.getAttribute("data-chart"));
    if (!figure) return;
    mark(date);
    openAround(figure);
    openTab(figure.closest(".tabs__panel"));
    window.ClimpactCharts.focusDate(figure, date).then(function () {
      scrollTo(figure);
      var plot = figure.querySelector("[data-chart-plot]");
      if (plot) plot.focus({ preventScroll: true });
    });
  });

  /* The row of a date in one table, loading the page that holds it when the table has
     more than one (a group's table may not hold the date at all: then none). */
  function rowIn(table, date) {
    var row = table.querySelector('tr[data-date="' + date + '"]');
    if (row || !window.htmx || table.getAttribute("data-pages") === "1") return Promise.resolve(row);
    var id = table.id;
    var src = table.getAttribute("data-src");
    src += (src.indexOf("?") < 0 ? "?" : "&") + "date=" + encodeURIComponent(date);
    return window.htmx.ajax("GET", src, { target: table, swap: "outerHTML" }).then(function () {
      var fresh = doc.getElementById(id);
      return fresh ? fresh.querySelector('tr[data-date="' + date + '"]') : null;
    });
  }

  function rowsFor(check, date) {
    var found = Array.prototype.slice.call(doc.querySelectorAll('[data-qc-finding][data-date="' + date + '"]'));
    var tables = doc.querySelectorAll('[data-qc-table][data-qc-check="' + check + '"]');
    return Promise.all(Array.prototype.map.call(tables, function (table) {
      return rowIn(table, date);
    })).then(function (rows) {
      return found.concat(rows);
    });
  }

  doc.addEventListener("climpact:chartpick", function (event) {
    var detail = event.detail || {};
    if (!detail.flagged) return;
    Promise.all(detail.checks.map(function (c) {
      return rowsFor(c, detail.date);
    })).then(function (lists) {
      mark(detail.date);
      var rows = [].concat.apply([], lists).filter(Boolean);
      rows.forEach(openAround);
      var first = rows[0];
      if (first) {
        scrollTo(first);
        first.focus({ preventScroll: true });
      }
    });
  });

  doc.addEventListener("htmx:afterSwap", function (event) {
    var table = event.target.closest && event.target.closest("[data-qc-table]");
    if (!table && event.target.matches && event.target.matches("[data-qc-table]")) table = event.target;
    var fresh = table && doc.getElementById(table.id);
    if (!fresh) return;
    reveal(fresh);
    if (selected) mark(selected);
    if (event.detail && event.detail.requestConfig && event.detail.requestConfig.elt && event.detail.requestConfig.elt.closest(".qc-pager")) {
      var region = fresh.querySelector("[data-qc-region]");
      if (region) region.focus();
    }
  });

  if (doc.readyState === "loading") {
    doc.addEventListener("DOMContentLoaded", function () {
      reveal(doc);
    });
  } else {
    reveal(doc);
  }
})();
