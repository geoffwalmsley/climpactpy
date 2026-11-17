/*
 * One index's page (#237, stations/result.html).
 *
 * Values or anomalies: the two charts are in the page and the toggle is two links (each
 * works without JavaScript); here a click shows its chart in place, marks its link
 * current and keeps the address, so the Annual/Monthly links keep the choice.
 *
 * Copy citation: without JavaScript a disclosure shows the text; here a button takes its
 * place and copies it, and says so (#announcer). If the clipboard refuses, the text is
 * shown as without JavaScript.
 */
(function () {
  "use strict";

  var doc = document;

  var group = doc.querySelector("[data-index-views]");
  if (group) {
    group.addEventListener("click", function (event) {
      var link = event.target.closest("[data-index-view-link]");
      if (!link || event.ctrlKey || event.metaKey || event.shiftKey) return;
      event.preventDefault();
      var view = link.getAttribute("data-index-view-link");
      doc.querySelectorAll("[data-index-view]").forEach(function (chart) {
        // An SVG element has no hidden property: set the attribute.
        chart.toggleAttribute("hidden", chart.getAttribute("data-index-view") !== view);
      });
      group.querySelectorAll("[data-index-view-link]").forEach(function (other) {
        if (other === link) other.setAttribute("aria-current", "true");
        else other.removeAttribute("aria-current");
      });
      doc.querySelectorAll("[data-index-period]").forEach(function (period) {
        var url = new URL(period.href);
        if (view === "anomaly") url.searchParams.set("view", "anomaly");
        else url.searchParams.delete("view");
        period.href = url.href;
      });
      history.replaceState(null, "", link.href);
    });
  }

  doc.querySelectorAll("[data-citation]").forEach(function (box) {
    var details = box.querySelector("details");
    var button = box.querySelector("[data-citation-copy]");
    var text = box.querySelector("[data-citation-text]").textContent.trim();
    if (!navigator.clipboard || !button) return;
    details.hidden = true;
    button.hidden = false;
    button.addEventListener("click", function () {
      navigator.clipboard.writeText(text).then(
        function () {
          var said = button.getAttribute("data-copied");
          var region = doc.getElementById("announcer");
          if (region) region.textContent = said;
          var label = button.textContent;
          button.textContent = said;
          setTimeout(function () { button.textContent = label; }, 2000);
        },
        function () {
          button.hidden = true;
          details.hidden = false;
          details.open = true;
        }
      );
    });
  });
})();
