/*
 * Step 2, Check quality (#77): links the check tables and the daily charts both ways.
 * Needs charts.js (window.ClimpactCharts) and htmx; without JavaScript the tables, pagers
 * (plain links) and downloads work and the "Show on chart" buttons stay hidden.
 *
 * - Table to chart: "Show on chart" ([data-qc-show], data-date, data-chart) opens the
 *   chart's tab, moves the chart to the date (ClimpactCharts.focusDate), marks the row and
 *   moves focus to the chart.
 * - Chart to table: a click on a chart ("climpact:chartpick") marks the rows of that date
 *   in the tables of the checks that flagged it, loading the page that holds it
 *   (stations:qc_table ?date=) when it is not shown, and scrolls to the first.
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

  function mark(date) {
    selected = date;
    Array.prototype.forEach.call(doc.querySelectorAll("[data-qc-table] tr[data-date]"), function (tr) {
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
    openTab(figure.closest(".tabs__panel"));
    window.ClimpactCharts.focusDate(figure, date).then(function () {
      scrollTo(figure);
      var plot = figure.querySelector("[data-chart-plot]");
      if (plot) plot.focus({ preventScroll: true });
    });
  });

  function rowsFor(check, date) {
    var table = doc.querySelector('[data-qc-table="' + check + '"]');
    if (!table) return Promise.resolve(null);
    var row = table.querySelector('tr[data-date="' + date + '"]');
    if (row || !window.htmx) return Promise.resolve(row);
    return window.htmx
      .ajax("GET", table.getAttribute("data-src") + "?date=" + encodeURIComponent(date), { target: table, swap: "outerHTML" })
      .then(function () {
        var fresh = doc.querySelector('[data-qc-table="' + check + '"]');
        return fresh ? fresh.querySelector('tr[data-date="' + date + '"]') : null;
      });
  }

  doc.addEventListener("climpact:chartpick", function (event) {
    var detail = event.detail || {};
    if (!detail.flagged) return;
    Promise.all(detail.checks.map(function (c) {
      return rowsFor(c, detail.date);
    })).then(function (rows) {
      mark(detail.date);
      var first = rows.filter(Boolean)[0];
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
