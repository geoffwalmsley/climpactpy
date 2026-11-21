// The index reference's Find and theme pills (#319, help/index_reference.html): filter the
// tables in place as you type or pick a theme, and keep the address in step (?q=, ?theme=)
// so it can be shared. Without JavaScript the form is a GET form and the server filters.
(function () {
  "use strict";
  var form = document.querySelector("[data-help-indices]");
  if (!form) return;
  var input = form.querySelector("input[name='q']");
  var pills = form.querySelectorAll("button[name='theme']");
  var count = form.querySelector("[data-help-indices-count]");
  var none = document.querySelector("[data-help-indices-none]");
  var sections = document.querySelectorAll("[data-help-indices-list] section[data-theme]");
  var submit = form.querySelector("[data-help-indices-submit]");
  if (submit) submit.hidden = true;
  var theme = "";
  pills.forEach(function (pill) { if (pill.getAttribute("aria-pressed") === "true") theme = pill.value; });

  function apply() {
    var words = input.value.toLowerCase().split(/\s+/).filter(Boolean);
    var shown = 0, total = 0;
    sections.forEach(function (section) {
      var visible = 0;
      section.querySelectorAll("tbody tr").forEach(function (row) {
        total += 1;
        var text = row.getAttribute("data-search") || "";
        var match = (!theme || section.getAttribute("data-theme") === theme) &&
          words.every(function (w) { return text.indexOf(w) >= 0; });
        row.hidden = !match;
        if (match) visible += 1;
      });
      section.hidden = visible === 0;
      shown += visible;
    });
    pills.forEach(function (pill) { pill.setAttribute("aria-pressed", String(pill.value === theme)); });
    if (count) {
      count.textContent = shown === total
        ? count.getAttribute("data-all")
        : count.getAttribute("data-some").replace("{shown}", shown);
    }
    if (none) none.hidden = shown > 0;
    var params = new URLSearchParams();
    if (input.value.trim()) params.set("q", input.value.trim());
    if (theme) params.set("theme", theme);
    var query = params.toString();
    history.replaceState(null, "", location.pathname + (query ? "?" + query : ""));
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (event.submitter && event.submitter.name === "theme") theme = event.submitter.value;
    apply();
  });
  input.addEventListener("input", apply);
})();
