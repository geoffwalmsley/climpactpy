/*
 * Quality (#77, #174, #202, #235, #264): the checks' rail and the selected check's
 * detail, and the links between its values and the daily charts under it. Needs charts.js
 * (window.ClimpactCharts) and htmx; without JavaScript each check in the rail is a link
 * to ?show=<id> (the server shows that detail), each value's date a link that selects it,
 * the sort, pager and downloads are plain links, the By calendar month table shows under
 * its chart and the "Show on the daily chart" buttons stay hidden.
 *
 * - The rail: a check's link ([data-qc-item]; Tab moves between them, Enter selects)
 *   shows its detail ([data-qc-detail]) in place of the one shown, marks the link
 *   (aria-current, is-selected), puts ?show=<id> in the address (replaceState, so it can
 *   be linked and reloaded) and announces the detail's title. When the detail is below
 *   the rail (a narrow screen) focus moves to its title, and "Back to the list"
 *   ([data-qc-back]) returns focus to the check. An address whose fragment names a
 *   detail (#check-<table>) shows that one.
 * - The values: a row's date (or anywhere on the row) selects its value, the sort and
 *   the pager change the table, each swapping the values fragment ([data-qc-table]) in
 *   place (htmx). Then the When chart's ring moves to the selected value, "Show on the
 *   daily chart" takes its date, the address takes the link's, the value's title is
 *   announced and focus stays on what was used.
 * - By calendar month: "Table" ([data-qc-months-toggle], aria-pressed) shows the table
 *   in place of the chart.
 * - List to chart: "Show on the daily chart" ([data-qc-show], data-date, data-chart)
 *   opens Details and the chart's tab, moves the chart to the date
 *   (ClimpactCharts.focusDate) and moves focus to the chart.
 * - Chart to list: a click on a flagged value of a chart ("climpact:chartpick") selects
 *   that value in the first check that found it (stations:qc_table ?date=, which answers
 *   a check that did not with no content) and shows its detail.
 */
(function () {
  "use strict";

  var doc = document;
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var behavior = reduce ? "auto" : "smooth";

  function all(selector, scope) {
    return Array.prototype.slice.call((scope || doc).querySelectorAll(selector));
  }

  function reveal(scope) {
    all("[data-qc-js]", scope).forEach(function (el) {
      el.hidden = false;
    });
  }

  function openAround(el) {
    for (var d = el.closest("details"); d; d = d.parentElement.closest("details")) d.open = true;
  }

  function say(text) {
    var said = doc.querySelector("[data-qc-said]");
    if (!said) return;
    said.textContent = "";
    window.setTimeout(function () {
      said.textContent = (text || "").replace(/\s+/g, " ").trim();
    }, 50);
  }

  function address(href) {
    if (!window.history || !window.history.replaceState) return;
    var url = new URL(href, window.location.href);
    url.hash = "";
    window.history.replaceState(window.history.state, "", url.toString());
  }

  /* The rail and its detail (#202, #264). */
  function detailOf(id) {
    return doc.querySelector('[data-qc-detail="' + id + '"]');
  }

  function show(id, options) {
    var panel = detailOf(id);
    if (!panel) return null;
    options = options || {};
    all("[data-qc-detail]").forEach(function (el) {
      el.hidden = el !== panel;
    });
    all("[data-qc-item]").forEach(function (a) {
      var on = a.getAttribute("data-qc-item") === id;
      a.classList.toggle("is-selected", on);
      if (on) a.setAttribute("aria-current", "true");
      else a.removeAttribute("aria-current");
    });
    var url = new URL(window.location.href);
    url.searchParams.set("show", id);
    address(url.toString());
    var title = panel.querySelector(".qc-detail__title");
    if (options.announce !== false && title) say(title.textContent);
    if (options.focus && title) {
      var rail = doc.querySelector(".qc-rail");
      var below = rail && rail.getBoundingClientRect().bottom <= panel.getBoundingClientRect().top + 1;
      if (below) {
        title.focus({ preventScroll: true });
        title.scrollIntoView({ behavior: behavior, block: "start" });
      } else {
        var box = panel.getBoundingClientRect();
        if (box.top >= window.innerHeight || box.bottom <= 0) panel.scrollIntoView({ behavior: behavior, block: "nearest" });
      }
    }
    return panel;
  }

  function plain(event) {
    return !(event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey);
  }

  doc.addEventListener("click", function (event) {
    var link = event.target.closest("[data-qc-item]");
    if (link && plain(event) && detailOf(link.getAttribute("data-qc-item"))) {
      event.preventDefault();
      show(link.getAttribute("data-qc-item"), { focus: true });
      return;
    }
    /* "Back to the list" (#235): focus on the check of the detail shown. */
    var back = event.target.closest("[data-qc-back]");
    if (back) {
      var item = doc.querySelector('[data-qc-item="' + back.getAttribute("data-qc-back") + '"]');
      if (!item) return;
      event.preventDefault();
      item.focus({ preventScroll: true });
      item.scrollIntoView({ behavior: behavior, block: "center" });
      return;
    }
    /* A click anywhere on a value's row selects it, as its date's link does. */
    var row = event.target.closest("[data-qc-table] tr[data-date]");
    if (row && !event.target.closest("a, button") && plain(event)) {
      var choose = row.querySelector("[data-qc-value]");
      if (choose) choose.click();
      return;
    }
    var toggle = event.target.closest("[data-qc-months-toggle]");
    if (toggle) {
      var on = toggle.getAttribute("aria-pressed") !== "true";
      toggle.setAttribute("aria-pressed", on ? "true" : "false");
      toggle.closest("[data-qc-months]").classList.toggle("is-table", on);
      return;
    }
    var button = event.target.closest("[data-qc-show]");
    if (!button || !window.ClimpactCharts) return;
    var figure = doc.getElementById(button.getAttribute("data-chart"));
    if (!figure) return;
    openAround(figure);
    var tabPanel = figure.closest(".tabs__panel");
    var tab = tabPanel && doc.getElementById(tabPanel.id + "-tab");
    if (tab && tab.getAttribute("aria-selected") !== "true") tab.click();
    window.ClimpactCharts.focusDate(figure, button.getAttribute("data-date")).then(function () {
      figure.scrollIntoView({ behavior: behavior, block: "center" });
      var plot = figure.querySelector("[data-chart-plot]");
      if (plot) plot.focus({ preventScroll: true });
    });
  });

  /* After the values fragment changes: the ring, "Show on the daily chart", the address,
     what is announced and where focus goes. */
  doc.addEventListener("htmx:afterSwap", function (event) {
    var target = event.detail && event.detail.target;
    var id = target && target.id;
    var fresh = id && doc.getElementById(id);
    if (!fresh || !fresh.matches("[data-qc-table]")) return;
    reveal(fresh);
    var panel = fresh.closest("[data-qc-detail]");
    var date = fresh.getAttribute("data-selected");
    var ring = panel && panel.querySelector("[data-qc-ring]");
    if (ring) {
      ring.setAttribute("cx", fresh.getAttribute("data-ring-x") || -20);
      ring.setAttribute("cy", fresh.getAttribute("data-ring-y") || -20);
    }
    var showButton = panel && panel.querySelector(".qc-detail__links [data-qc-show]");
    if (showButton && date) {
      showButton.setAttribute("data-date", date);
      showButton.setAttribute("data-chart", fresh.getAttribute("data-chart"));
    }
    var elt = event.detail.requestConfig && event.detail.requestConfig.elt;
    if (!elt || !elt.getAttribute) return;
    if (elt.getAttribute("href")) address(elt.getAttribute("href"));
    var focus = null;
    if (elt.hasAttribute("data-qc-value")) {
      focus = fresh.querySelector('[data-qc-value="' + date + '"]');
      var title = fresh.querySelector("[data-qc-value-title]");
      if (title) say(title.textContent);
    } else if (elt.hasAttribute("data-qc-sort")) {
      focus = fresh.querySelector("[data-qc-sort][aria-current]");
    } else if (elt.hasAttribute("data-qc-page")) {
      focus = fresh.querySelector("[data-qc-region]");
    }
    if (focus) focus.focus({ preventScroll: true });
  });

  /* A flag picked on a chart: its value selected in the first check that found it. */
  doc.addEventListener("climpact:chartpick", function (event) {
    var detail = event.detail || {};
    if (!detail.flagged || !window.htmx) return;
    var tables = [];
    detail.checks.forEach(function (c) {
      tables = tables.concat(all('[data-qc-table][data-qc-check="' + c + '"]'));
    });
    var date = detail.date;
    Promise.all(tables.map(function (table) {
      if (table.getAttribute("data-pages") === "1" && !table.querySelector('tr[data-date="' + date + '"]')) return null;
      var id = table.id;
      var src = table.getAttribute("data-src");
      src += (src.indexOf("?") < 0 ? "?" : "&") + "date=" + encodeURIComponent(date);
      return window.htmx.ajax("GET", src, { target: "#" + id, swap: "outerHTML" }).then(function () {
        var now = doc.getElementById(id);
        return now && now.getAttribute("data-selected") === date ? now : null;
      });
    })).then(function (found) {
      var table = found.filter(Boolean)[0];
      if (!table) return;
      var panel = table.closest("[data-qc-detail]");
      show(panel.getAttribute("data-qc-detail"));
      var link = table.querySelector('[data-qc-value="' + date + '"]');
      if (!link) return;
      link.scrollIntoView({ behavior: behavior, block: "center" });
      link.focus({ preventScroll: true });
    });
  });

  function start() {
    reveal(doc);
    // An address that names a detail by its fragment (#check-<table>).
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
