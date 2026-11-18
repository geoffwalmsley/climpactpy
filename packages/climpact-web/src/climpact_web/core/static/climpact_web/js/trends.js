/*
 * Trends across stations (#238, stations/_trends.html).
 *
 * Each column's code in the trend grid is a link that selects the column (?index=), which
 * works without JavaScript; here a click shows that column's interval plot in place
 * (every column's plot is in the page), marks the column and keeps the address, so a
 * reload shows the same one. Delegated from the document: the overview swaps the section
 * in with its progress while stations are calculated.
 */
(function () {
  "use strict";

  document.addEventListener("click", function (event) {
    var link = event.target.closest("[data-trend-pick]");
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    var section = link.closest("[data-trends]");
    if (!section) return;
    var code = link.getAttribute("data-trend-pick");
    var found = false;
    section.querySelectorAll("[data-trend-plot]").forEach(function (plot) {
      var on = plot.getAttribute("data-trend-plot") === code;
      plot.hidden = !on;
      found = found || on;
    });
    if (!found) return; // no plot in the page: follow the link
    event.preventDefault();
    section.querySelectorAll("[data-trend-col]").forEach(function (column) {
      var on = column.getAttribute("data-trend-col") === code;
      column.toggleAttribute("data-selected", on);
      var pick = column.querySelector("[data-trend-pick]");
      if (on) pick.setAttribute("aria-current", "true");
      else pick.removeAttribute("aria-current");
    });
    var chosen = section.querySelector('input[name="index"]');
    if (chosen) chosen.value = code;
    history.replaceState(null, "", link.href);
  });
})();
