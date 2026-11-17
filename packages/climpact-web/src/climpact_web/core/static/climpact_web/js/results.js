/* The results catalogue (#78, #200): one table of every index, filtered as you type (a
   theme chip, "Significant only", a search) and sorted by a column. Without JavaScript the
   filters are a form sent to the page and each column header a link to the page sorted by
   it; here the headers become buttons, the rows are filtered and sorted in place as the
   server would, aria-sort moves to the sorted column, and the live line under the filters
   says how many rows show and how they are sorted. No dependencies, no network requests. */
(function () {
  "use strict";

  function init() {
    var form = document.querySelector("[data-results-filter]");
    var table = document.querySelector("[data-results-table]");
    if (!form || !table) return;
    var body = table.tBodies[0];
    var rows = Array.prototype.slice.call(body.rows);
    var headers = Array.prototype.slice.call(table.querySelectorAll("th[data-sort-key]"));
    var count = document.querySelector("[data-results-count]");
    var empty = document.querySelector("[data-results-empty]");
    var submit = form.querySelector("[data-results-submit]");
    if (submit) submit.hidden = true;
    var sort = { key: "", dir: "" };
    headers.forEach(function (th) {
      if (th.hasAttribute("aria-sort")) {
        sort = { key: th.getAttribute("data-sort-key"), dir: th.getAttribute("aria-sort") };
      }
    });
    // The no-JavaScript sort is kept by hidden fields; from here on it is in `sort`.
    Array.prototype.slice.call(form.querySelectorAll("input[type=hidden]")).forEach(
      function (input) { input.remove(); }
    );
    var shown = rows.filter(function (row) { return !row.hidden; }).length;

    function label(th) {
      return th.querySelector(".sort").textContent.trim();
    }

    function say() {
      if (!count) return;
      var text = count.getAttribute("data-template")
        .replace("%(shown)s", shown).replace("%(total)s", rows.length);
      var th = headers.filter(function (h) { return h.getAttribute("data-sort-key") === sort.key; })[0];
      if (th) {
        text += " " + table.getAttribute("data-" + sort.dir).replace("%(column)s", label(th));
      }
      count.textContent = text;
    }

    function remember() {
      var data = new FormData(form);
      var params = new URLSearchParams();
      if (String(data.get("q") || "").trim()) params.set("q", data.get("q"));
      if (data.get("theme")) params.set("theme", data.get("theme"));
      if (data.get("significant") === "1") params.set("significant", "1");
      if (sort.key) {
        params.set("sort", sort.key);
        params.set("dir", sort.dir);
      }
      var query = params.toString();
      history.replaceState(null, "", location.pathname + (query ? "?" + query : "") + location.hash);
    }

    function filter() {
      var data = new FormData(form);
      var words = String(data.get("q") || "").toLowerCase().split(/\s+/).filter(Boolean);
      var theme = String(data.get("theme") || "");
      var significant = data.get("significant") === "1";
      shown = 0;
      rows.forEach(function (row) {
        var text = row.getAttribute("data-search") || "";
        var hide = (theme && row.getAttribute("data-chip") !== theme) ||
          (significant && !row.hasAttribute("data-significant")) ||
          words.some(function (w) { return text.indexOf(w) === -1; });
        row.hidden = hide;
        if (!hide) shown += 1;
      });
      if (empty) empty.hidden = shown > 0;
      say();
      remember();
    }

    // As stations.views_indices.sort_cards: ties keep the catalogue's order (names tie by
    // code), and rows without a trend stay last when sorting by the trend.
    function value(row, key) {
      if (key === "name" || key === "code") return row.getAttribute("data-" + key);
      if (key === "trend") return row.getAttribute("data-trend");
      return Number(row.getAttribute("data-rank"));
    }

    function order() {
      var sign = sort.dir === "descending" ? -1 : 1;
      rows.sort(function (a, b) {
        var by = 0;
        if (sort.key === "name" || sort.key === "code") {
          // Lower case, by code point, as the server's casefold sort.
          var p = value(a, sort.key).toLowerCase(), q = value(b, sort.key).toLowerCase();
          if (p === q && sort.key === "name") {
            // Short names repeat (#218): by code within a name, as the server.
            p = value(a, "code").toLowerCase();
            q = value(b, "code").toLowerCase();
          }
          by = sign * (p < q ? -1 : p > q ? 1 : 0);
        } else if (sort.key === "trend") {
          var x = value(a, "trend"), y = value(b, "trend");
          if (x === "" || y === "") by = (x === "") - (y === "");
          else by = sign * (Number(x) - Number(y));
        } else if (sort.key) {
          by = sign * (value(a, sort.key) - value(b, sort.key));
        }
        return by || Number(a.getAttribute("data-order")) - Number(b.getAttribute("data-order"));
      });
      rows.forEach(function (row) { body.appendChild(row); });
      headers.forEach(function (th) {
        if (th.getAttribute("data-sort-key") === sort.key) th.setAttribute("aria-sort", sort.dir);
        else th.removeAttribute("aria-sort");
      });
      say();
      remember();
    }

    headers.forEach(function (th) {
      var link = th.querySelector("a.sort");
      if (!link) return;
      var button = document.createElement("button");
      button.type = "button";
      button.className = "sort";
      button.textContent = link.textContent;
      link.replaceWith(button);
      button.addEventListener("click", function () {
        var key = th.getAttribute("data-sort-key");
        var dir = th.getAttribute("data-sort-first");
        if (sort.key === key) dir = sort.dir === "ascending" ? "descending" : "ascending";
        sort = { key: key, dir: dir };
        order();
      });
    });

    form.addEventListener("input", filter);
    form.addEventListener("change", filter);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      filter();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
