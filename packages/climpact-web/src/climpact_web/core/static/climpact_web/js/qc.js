/*
 * Quality (#77, #174, #202, #235): the worklist and its detail pane, and the links between
 * the findings and the daily charts under the worklist. Needs charts.js (window.ClimpactCharts) and htmx;
 * without JavaScript each row of the list is a link to ?show=<id> (the server shows that
 * detail), the tables, pagers (plain links) and downloads work and the "Show on the
 * daily chart" buttons stay hidden.
 *
 * - The list: a row's link ([data-qc-item]; Tab moves between them, Enter selects)
 *   shows its detail ([data-qc-detail]) in place of the one shown, marks the link
 *   (aria-current) and its row (is-selected), puts ?show=<id> in the address
 *   (replaceState, so it can be linked and reloaded) and announces the detail's title.
 *   Beside the list the pane stays in view (sticky); should it still be out of view, it
 *   is scrolled into view, focus staying on the row. When the detail is below the list
 *   (a narrow screen) focus moves to its title, and "Back to the list" ([data-qc-back])
 *   returns focus to the row. An address whose fragment names a detail
 *   (#check-<table>) shows that one.
 * - List to chart: "Show on the daily chart" ([data-qc-show], data-date, data-chart)
 *   opens Details and the chart's tab, moves the chart to the date
 *   (ClimpactCharts.focusDate), marks the row and moves focus to the chart.
 * - Chart to list: a click on a flagged value of a chart ("climpact:chartpick") shows the
 *   finding of that date, or the group whose table holds it (loading the page that
 *   holds it, stations:qc_table ?date=), marks its row and focuses it.
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
    Array.prototype.forEach.call(doc.querySelectorAll("[data-qc-table] tr[data-date]"), function (tr) {
      var on = tr.getAttribute("data-date") === date;
      tr.classList.toggle("is-selected", on);
      if (on) tr.setAttribute("aria-current", "true");
      else tr.removeAttribute("aria-current");
    });
  }

  /* The list and its detail (#202). */
  function detailOf(id) {
    return doc.querySelector('[data-qc-detail="' + id + '"]');
  }

  function show(id, options) {
    var panel = detailOf(id);
    if (!panel) return null;
    options = options || {};
    Array.prototype.forEach.call(doc.querySelectorAll("[data-qc-detail]"), function (el) {
      el.hidden = el !== panel;
    });
    Array.prototype.forEach.call(doc.querySelectorAll("[data-qc-item]"), function (a) {
      var on = a.getAttribute("data-qc-item") === id;
      var row = a.closest("tr");
      if (row) row.classList.toggle("is-selected", on);
      if (on) a.setAttribute("aria-current", "true");
      else a.removeAttribute("aria-current");
    });
    if (window.history && window.history.replaceState) {
      var url = new URL(window.location.href);
      url.searchParams.set("show", id);
      url.hash = "";
      window.history.replaceState(window.history.state, "", url.toString());
    }
    var title = panel.querySelector(".qc-detail__title");
    var said = doc.querySelector("[data-qc-said]");
    if (said && options.announce !== false) {
      said.textContent = "";
      window.setTimeout(function () {
        said.textContent = title ? title.textContent.replace(/\s+/g, " ").trim() : "";
      }, 50);
    }
    if (options.focus && title) {
      var list = doc.querySelector(".qc-work__list");
      var below = list && list.getBoundingClientRect().bottom <= panel.getBoundingClientRect().top + 1;
      if (below) {
        title.focus({ preventScroll: true });
        title.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
      } else {
        var box = panel.getBoundingClientRect();
        if (box.top >= window.innerHeight || box.bottom <= 0) {
          panel.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "nearest" });
        }
      }
    }
    return panel;
  }

  doc.addEventListener("click", function (event) {
    var link = event.target.closest("[data-qc-item]");
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (!detailOf(link.getAttribute("data-qc-item"))) return;
    event.preventDefault();
    show(link.getAttribute("data-qc-item"), { focus: true });
  });

  /* "Back to the list" (#235): focus on the row of the detail shown. */
  doc.addEventListener("click", function (event) {
    var back = event.target.closest("[data-qc-back]");
    if (!back) return;
    var link = doc.querySelector('[data-qc-item="' + back.getAttribute("data-qc-back") + '"]');
    if (!link) return;
    event.preventDefault();
    link.focus({ preventScroll: true });
    link.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "center" });
  });

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
    var tables = doc.querySelectorAll('[data-qc-table][data-qc-check="' + check + '"]');
    return Promise.all(Array.prototype.map.call(tables, function (table) {
      return rowIn(table, date);
    }));
  }

  /* A flag picked on a chart: the finding of that date when it is in the list, or else
     the first group or table that holds it. */
  doc.addEventListener("climpact:chartpick", function (event) {
    var detail = event.detail || {};
    if (!detail.flagged) return;
    var finding = null;
    detail.checks.some(function (c) {
      finding = detailOf(c + "-" + detail.date);
      return !!finding;
    });
    if (finding) {
      mark(detail.date);
      show(finding.getAttribute("data-qc-detail"));
      var title = finding.querySelector(".qc-detail__title");
      scrollTo(finding);
      if (title) title.focus({ preventScroll: true });
      return;
    }
    Promise.all(detail.checks.map(function (c) {
      return rowsFor(c, detail.date);
    })).then(function (lists) {
      mark(detail.date);
      var rows = [].concat.apply([], lists).filter(Boolean);
      var first = rows[0];
      if (!first) return;
      var panel = first.closest("[data-qc-detail]");
      if (panel) show(panel.getAttribute("data-qc-detail"));
      openAround(first);
      scrollTo(first);
      first.focus({ preventScroll: true });
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

  function start() {
    reveal(doc);
    // An address that names a detail by its fragment (#check-<table>, #finding-<id>).
    var hash = window.location.hash.slice(1);
    var target = hash && doc.getElementById(decodeURIComponent(hash));
    if (target && target.matches("[data-qc-detail]") && target.hidden) {
      show(target.getAttribute("data-qc-detail"), { announce: false });
      target.scrollIntoView();
    }
  }

  if (doc.readyState === "loading") {
    doc.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
