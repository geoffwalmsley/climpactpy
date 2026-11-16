/* The results dashboard's filters (#78): find an index by name or words, show one theme
   (#175), or only significant trends, as you type. Without JavaScript the same form is sent and
   the server filters the cards. The groups are collapsed <details> (#113): a filter opens
   the groups it shows (and closes them again when cleared), and a #group-... link opens
   its group. No dependencies, no network requests. */
(function () {
  "use strict";

  function init() {
    var form = document.querySelector("[data-results-filter]");
    if (!form) return;
    var cards = Array.prototype.slice.call(document.querySelectorAll(".index-card"));
    var sections = Array.prototype.slice.call(document.querySelectorAll("[data-results-section]"));
    var count = document.querySelector("[data-results-count]");
    var empty = document.querySelector("[data-results-empty]");
    var submit = form.querySelector("[data-results-submit]");
    if (submit) submit.hidden = true;

    function openTarget() {
      var target = location.hash && document.getElementById(location.hash.slice(1));
      var group = target && target.closest("details");
      if (group) group.open = true;
    }
    openTarget();
    window.addEventListener("hashchange", openTarget);

    function apply() {
      var data = new FormData(form);
      var words = String(data.get("q") || "").toLowerCase().split(/\s+/).filter(Boolean);
      var theme = String(data.get("theme") || "");
      var significant = data.get("significant") === "1";
      var shown = 0;
      cards.forEach(function (card) {
        var text = card.getAttribute("data-search") || "";
        var hide = (theme && card.getAttribute("data-index-theme") !== theme) ||
          (significant && !card.hasAttribute("data-significant")) ||
          words.some(function (w) { return text.indexOf(w) === -1; });
        card.hidden = hide;
        if (!hide) shown += 1;
      });
      var filtering = words.length || theme || significant;
      sections.forEach(function (section) {
        section.hidden = !section.querySelector(".index-card:not([hidden])");
        if (filtering && !section.hidden && !section.open) {
          section.open = true;
          section.setAttribute("data-auto-open", "");
        } else if (!filtering && section.hasAttribute("data-auto-open")) {
          section.open = false;
          section.removeAttribute("data-auto-open");
        }
      });
      if (count) {
        count.textContent = count.getAttribute("data-template")
          .replace("%(shown)s", shown).replace("%(total)s", cards.length);
      }
      if (empty) empty.hidden = shown > 0;
      var params = new URLSearchParams();
      if (words.length) params.set("q", data.get("q"));
      if (theme) params.set("theme", theme);
      if (significant) params.set("significant", "1");
      var query = params.toString();
      history.replaceState(null, "", location.pathname + (query ? "?" + query : ""));
    }

    form.addEventListener("input", apply);
    form.addEventListener("change", apply);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      apply();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
