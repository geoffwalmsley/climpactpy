/*
 * A gridded run's Map (#295, #296, gridded/_map.html). Without JavaScript every control is a
 * link or a GET form; here:
 *
 * - The rail's Find filters the indices as you type.
 * - Links and forms in the map (an index, the frequency, the stepper, the scale, Go to)
 *   swap the map block in place (X-Climpact-Part: map) and keep the address; Back and
 *   Forward show the earlier state.
 * - The map reads out the cell under the pointer (a line under it and a tooltip), from
 *   the map's values (gridded:map_values, float32, fetched when first needed); a click
 *   selects the cell. The map is one focusable group: the arrow keys move the selection
 *   (Shift: ten cells), a polite live region reads out the cell and its value, and the
 *   pane follows after a pause (Enter at once). The pane alone is swapped
 *   (X-Climpact-Part: pane), and the address, links and forms take the new cell; a cell
 *   chosen while the pane shows the mean over the grid shows the cell's series.
 * - The read-out follows the view (#296): "anomaly +1.2 °C", "trend +0.25 °C/decade,
 *   significant" (on Trend the values hold a second grid, 1 where the cell's interval
 *   excludes zero).
 * - Download ▾ closes on Escape and on a click elsewhere.
 * - When the run finishes, the stages' poll (#294) puts an empty map in their place
 *   (data-gmap-load), which is filled at once with the map part, as a link would.
 */
(function () {
  "use strict";

  var doc = document;
  var lang = doc.documentElement.lang || "en";
  var formats = {};
  var paneTimer = null;
  var paneRequest = 0;

  // The number rules (core/numbers.py, #226): U+2212 for minus, never "−0".
  function num(v, signed) {
    var d = Math.abs(v) < 10 ? 2 : 1;
    if (!formats[d]) formats[d] = new Intl.NumberFormat(lang, { maximumFractionDigits: d });
    var text = formats[d].format(v);
    if (/^-?0([.,]0*)?$/.test(text)) return text.replace(/^-/, "");
    if (signed && v > 0) return "+" + text;
    return text.replace(/^-/, "−");
  }

  function root() {
    return doc.getElementById("gridded-map");
  }

  /* ---- Find ---- */

  function filterRail(scope) {
    var input = scope.querySelector("#gmap-find");
    if (!input) return;
    var words = input.value.trim().toLowerCase();
    var shown = 0;
    scope.querySelectorAll("[data-gmap-group]").forEach(function (group) {
      var visible = 0;
      group.querySelectorAll("[data-gmap-entry]").forEach(function (li) {
        var match = !words || li.getAttribute("data-gmap-entry").indexOf(words) !== -1;
        li.hidden = !match;
        if (match) visible++;
      });
      group.hidden = visible === 0;
      shown += visible;
    });
    var none = scope.querySelector("[data-gmap-none]");
    if (none) none.hidden = shown > 0;
  }

  /* ---- Swapping the map block or the pane ---- */

  function fetchPart(url, part) {
    return fetch(url, { credentials: "same-origin", headers: { "X-Climpact-Part": part } }).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.text();
    });
  }

  function fragment(html) {
    var box = doc.createElement("div");
    box.innerHTML = html;
    return box.firstElementChild;
  }

  function hydrate(el) {
    if (window.ClimpactCharts) window.ClimpactCharts.hydrate(el);
  }

  function navigate(url, opts) {
    opts = opts || {};
    var old = root();
    if (!old) {
      location.href = url;
      return;
    }
    var find = old.querySelector("#gmap-find");
    var query = find ? find.value : "";
    var rail = old.querySelector(".gmap-rail__body");
    var railTop = rail ? rail.scrollTop : 0;
    old.setAttribute("aria-busy", "true");
    fetchPart(url, "map")
      .then(function (html) {
        var next = fragment(html);
        old.replaceWith(next);
        if (!opts.back) history.pushState({ gmap: true }, "", url);
        var input = next.querySelector("#gmap-find");
        if (input && query) {
          input.value = query;
          filterRail(next);
        }
        var body = next.querySelector(".gmap-rail__body");
        if (body) body.scrollTop = railTop;
        init(next);
        hydrate(next);
        var focus = opts.focus && next.querySelector(opts.focus);
        if (!focus && opts.focusTitle !== false) focus = next.querySelector("#map-title");
        if (focus && !opts.back) focus.focus({ preventScroll: true });
      })
      .catch(function () {
        location.href = url;
      });
  }

  function withCell(href, cell) {
    var url = new URL(href, location.href);
    url.searchParams.set("cell", cell[0] + "," + cell[1]);
    url.searchParams.delete("goto");
    url.searchParams.delete("series");
    return url.href;
  }

  function loadPane(scope, grid, cell) {
    var url = withCell(location.href, cell);
    var request = ++paneRequest;
    var old = scope.querySelector("[data-gmap-pane]");
    if (old) old.setAttribute("aria-busy", "true");
    fetchPart(url, "pane")
      .then(function (html) {
        if (request !== paneRequest) return;
        var pane = scope.querySelector("[data-gmap-pane]");
        var next = fragment(html);
        if (pane) pane.replaceWith(next);
        history.replaceState({ gmap: true }, "", url);
        // Links and forms keep the cell chosen.
        scope.querySelectorAll("a[data-gmap-nav]").forEach(function (a) {
          a.href = withCell(a.getAttribute("href"), cell);
        });
        scope.querySelectorAll("form input[name=cell]").forEach(function (input) {
          input.value = cell[0] + "," + cell[1];
        });
        next.querySelectorAll("form input[name=cell]").forEach(function (input) {
          input.value = cell[0] + "," + cell[1];
        });
        hydrate(next);
      })
      .catch(function () {
        location.href = url;
      });
  }

  /* ---- The map ---- */

  function init(scope) {
    if (!scope) return;
    filterRail(scope);
    var data = scope.querySelector("#gmap-data");
    var svg = scope.querySelector("[data-gmap-svg]");
    if (!data || !svg) return;
    var grid = JSON.parse(data.textContent);
    var frame = svg.parentNode;
    var tip = scope.querySelector("[data-gmap-tip]");
    var readout = scope.querySelector("[data-gmap-readout]");
    var status = scope.querySelector("[data-gmap-status]");
    var hover = svg.querySelector("[data-gmap-hover]");
    var selected = svg.querySelectorAll("[data-gmap-selected]");
    var values = null;
    var loading = null;
    var cw = grid.w / grid.nx, ch = grid.h / grid.ny;
    var sel = [grid.rows.indexOf(grid.cell[0]), grid.cols.indexOf(grid.cell[1])];
    var hint = readout ? readout.textContent : "";

    svg.setAttribute("role", "group");
    svg.setAttribute("tabindex", "0");
    svg.setAttribute("aria-roledescription", grid.roledescription || "map");
    svg.setAttribute("aria-describedby", "gmap-keys");
    if (readout) readout.hidden = false;

    function load() {
      if (!loading) {
        loading = fetch(grid.values, { credentials: "same-origin" })
          .then(function (r) {
            if (!r.ok) throw new Error(r.status);
            return r.arrayBuffer();
          })
          .then(function (buffer) {
            values = new Float32Array(buffer);
          })
          .catch(function () {
            values = null;
          });
      }
      return loading;
    }

    function text(r, c) {
      var where = grid.lat[grid.rows[r]] + " " + grid.lon[grid.cols[c]];
      var n = grid.nx * grid.ny;
      var v = values ? values[r * grid.nx + c] : NaN;
      if (!values) return where;
      if (v !== v) return where + " · " + grid.noValue;
      var words = where + " · " + grid.code + (grid.what ? " " + grid.what : "") + " " + num(v, grid.signed);
      words += grid.units ? (grid.units === "%" ? "%" : " " + grid.units) : "";
      if (grid.significant && values.length === 2 * n) {
        words += ", " + (values[n + r * grid.nx + c] === 1 ? grid.significant : grid.notSignificant);
      }
      return words;
    }

    function cellAt(event) {
      var m = svg.getScreenCTM();
      if (!m) return null;
      var pt = svg.createSVGPoint();
      pt.x = event.clientX;
      pt.y = event.clientY;
      var p = pt.matrixTransform(m.inverse());
      var c = Math.floor((p.x - grid.left) / cw), r = Math.floor((p.y - grid.top) / ch);
      if (r < 0 || c < 0 || r >= grid.ny || c >= grid.nx) return null;
      return [r, c];
    }

    function place(rect, r, c) {
      rect.setAttribute("x", (grid.left + c * cw).toFixed(2));
      rect.setAttribute("y", (grid.top + r * ch).toFixed(2));
    }

    function select(r, c, announce, now) {
      sel = [r, c];
      selected.forEach(function (rect) {
        place(rect, r, c);
      });
      var cell = [grid.rows[r], grid.cols[c]];
      if (readout) readout.textContent = grid.selected.replace("%(where)s", text(r, c));
      if (announce && status) status.textContent = text(r, c);
      clearTimeout(paneTimer);
      paneTimer = setTimeout(function () {
        loadPane(scope, grid, cell);
      }, now ? 0 : 600);
    }

    svg.addEventListener("pointermove", function (event) {
      var at = cellAt(event);
      if (!at) {
        hover.setAttribute("hidden", "");
        tip.hidden = true;
        return;
      }
      load().then(function () {
        hover.removeAttribute("hidden");
        place(hover, at[0], at[1]);
        var words = text(at[0], at[1]);
        if (readout) readout.textContent = words;
        tip.textContent = words;
        tip.hidden = false;
        var box = frame.getBoundingClientRect();
        var x = event.clientX - box.left + 14, y = event.clientY - box.top + 14;
        if (x + tip.offsetWidth > box.width) x = event.clientX - box.left - tip.offsetWidth - 10;
        tip.style.left = x + "px";
        tip.style.top = y + "px";
      });
    });

    svg.addEventListener("pointerleave", function () {
      hover.setAttribute("hidden", "");
      tip.hidden = true;
      if (readout) readout.textContent = values ? grid.selected.replace("%(where)s", text(sel[0], sel[1])) : hint;
    });

    svg.addEventListener("click", function (event) {
      var at = cellAt(event);
      if (!at) return;
      load().then(function () {
        select(at[0], at[1], false, true);
      });
    });

    svg.addEventListener("focus", function () {
      load().then(function () {
        if (readout) readout.textContent = grid.selected.replace("%(where)s", text(sel[0], sel[1]));
      });
    });

    svg.addEventListener("keydown", function (event) {
      var step = event.shiftKey ? 10 : 1;
      var r = sel[0], c = sel[1];
      switch (event.key) {
        case "ArrowLeft": c = Math.max(0, c - step); break;
        case "ArrowRight": c = Math.min(grid.nx - 1, c + step); break;
        case "ArrowUp": r = Math.max(0, r - step); break;
        case "ArrowDown": r = Math.min(grid.ny - 1, r + step); break;
        case "Enter":
          event.preventDefault();
          select(sel[0], sel[1], true, true);
          return;
        default:
          return;
      }
      event.preventDefault();
      load().then(function () {
        select(r, c, true, false);
      });
    });
  }

  /* ---- Events ---- */

  doc.addEventListener("click", function (event) {
    var link = event.target.closest("a[data-gmap-nav]");
    if (link && root() && root().contains(link)) {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button) return;
      event.preventDefault();
      var step = link.getAttribute("data-gmap-step");
      var focus = step ? "[data-gmap-step=" + step + "]" : null;
      if (!focus && link.classList.contains("gmap-rail__item")) focus = ".gmap-rail__item[aria-current]";
      if (!focus && link.hasAttribute("data-gmap-series")) focus = "[data-gmap-series][aria-current]";
      if (!focus && link.classList.contains("segmented__item")) focus = ".gmap-controls .segmented__item[aria-current]";
      navigate(link.href, { focus: focus });
      return;
    }
    // Download ▾: a click elsewhere closes it.
    doc.querySelectorAll("details[data-gmap-menu][open]").forEach(function (menu) {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });

  doc.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    doc.querySelectorAll("details[data-gmap-menu][open]").forEach(function (menu) {
      menu.open = false;
      menu.querySelector("summary").focus();
    });
  });

  doc.addEventListener("input", function (event) {
    if (event.target.id === "gmap-find" && root()) filterRail(root());
  });

  doc.addEventListener("submit", function (event) {
    var form = event.target;
    if (!root() || !root().contains(form)) return;
    if (form.matches("[data-gmap-find]")) {
      event.preventDefault();
      return;
    }
    if (form.matches("[data-gmap-goto]")) {
      event.preventDefault();
      var url = new URL(form.action, location.href);
      new FormData(form).forEach(function (value, key) {
        if (key !== "cell") url.searchParams.set(key, value);
      });
      navigate(url.href, { focus: "#cell-title", focusTitle: false });
    }
  });

  window.addEventListener("popstate", function () {
    if (root()) navigate(location.href, { back: true });
  });

  doc.addEventListener("htmx:load", function (event) {
    var el = event.target;
    if (el.id !== "gridded-map") return;
    if (el.hasAttribute("data-gmap-load")) navigate(location.href, { back: true });
    else init(el);
  });

  init(root());
})();
