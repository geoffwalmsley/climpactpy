/*
 * A read-out for the charts drawn on the server (#283): the Indices' detail pane and
 * Quality's check charts. Each <svg data-readout='{...}'> (stations/_readout.html under
 * it) gets a crosshair and the values under the pointer or the keyboard's cursor:
 *
 * - pointer: the nearest value (by x, or by distance with "near": "xy");
 * - keyboard: the chart is focusable; the left and right arrow keys move from value to
 *   value, Home and End go to the first and last, Enter (or a click) acts on the value
 *   when the chart has an action. Each move is announced in the status line.
 * - actions: "href" opens it with the value's key appended (the Indices: the index page
 *   at that year, ?at=1944); "pick" dispatches "climpact:readoutpick" on the svg
 *   (bubbling, detail {when}; Quality's When chart selects that value's row, qc.js).
 *
 * The data, in the svg's box units, is either "points": [[x, y or null, when, text]], or
 * a series: "v" (values, null for missing; or "src", the URL of the series' chart data,
 * whose "y" is fetched when the chart is first used), x from "x0" and "dx" (times "d",
 * day offsets, when given), y from "low", "high", "top", "bottom"; "when" names each
 * value: {step:
 * "year" | "month" | "day" | "date", first} as the page's tables write them (1944,
 * 1944-03, the "day" pattern, 1961-03-04); "label" and "unit" write the value ("TXx
 * 41.2 °C", by the number rules of core/numbers.py), "missing" a missing one. "ring":
 * false draws the crosshair only. Without JavaScript the chart is the server's image,
 * unchanged. The JSON is read when the chart is first used.
 */
(function () {
  "use strict";

  var doc = document;
  var NS = "http://www.w3.org/2000/svg";
  var lang = doc.documentElement.lang || "en";
  var formats = {};

  // The number rules (core/numbers.py, #226), as charts.js: U+2212 for minus, never "−0".
  function num(v) {
    var d = Math.abs(v) < 10 ? 2 : 1;
    if (!formats[d]) formats[d] = new Intl.NumberFormat(lang, { maximumFractionDigits: d });
    var text = formats[d].format(v);
    if (/^-0(\D0*)?$/.test(text)) return text.slice(1);
    return text.replace(/^-/, "−");
  }

  function withUnit(text, unit) {
    return text + (!unit ? "" : unit === "%" ? "%" : " " + unit);
  }

  function pad(n) {
    return (n < 10 ? "0" : "") + n;
  }

  function whenOf(spec, i, offset) {
    var first = spec.first;
    if (spec.step === "year") return String(+first + i);
    if (spec.step === "month") {
      var parts = String(first).split("-"), m = +parts[0] * 12 + (+parts[1] - 1) + i;
      return Math.floor(m / 12) + "-" + pad((m % 12) + 1);
    }
    if (spec.step === "day") return spec.pattern.replace("%s", String(+first + i));
    var day = new Date(Date.parse(first + "T00:00:00Z") + offset * 86400000);
    return day.toISOString().slice(0, 10);
  }

  function expand(data) {
    if (data.points) return data.points;
    var out = [], span = data.high - data.low || 1;
    data.v.forEach(function (v, i) {
      var step = data.d ? data.d[i] : i;
      var y = v == null || data.ring === false ? null : data.bottom - ((v - data.low) / span) * (data.bottom - data.top);
      var text = v == null ? data.missing : (data.label ? data.label + " " : "") + withUnit(num(v), data.unit);
      out.push([data.x0 + step * data.dx, y, whenOf(data.when, i, step), text]);
    });
    return out;
  }

  function el(name, attrs) {
    var node = doc.createElementNS(NS, name);
    Object.keys(attrs).forEach(function (k) {
      node.setAttribute(k, attrs[k]);
    });
    return node;
  }

  function Readout(svg) {
    this.svg = svg;
    this.figure = svg.closest("figure") || svg.parentNode;
    this.text = this.figure.querySelector("[data-readout-text]");
    this.status = this.figure.querySelector("[data-readout-status]");
    this.cursor = null;
  }

  /* The points, read (and fetched, with "src") when the chart is first used; until
     then [] (the chart shows nothing). */
  Readout.prototype.data = function () {
    if (!this.spec) {
      var self = this;
      this.spec = JSON.parse(this.svg.getAttribute("data-readout"));
      this.points = [];
      var box = this.svg.viewBox.baseVal, spec = this.spec;
      this.mark = el("g", { class: "readout-mark", "aria-hidden": "true", display: "none" });
      this.line = el("line", { class: "readout-mark__line", y1: spec.top != null ? spec.top : 0, y2: spec.bottom != null ? spec.bottom : box.height });
      this.ring = el("circle", { class: "readout-mark__ring", r: 5 });
      this.mark.appendChild(this.line);
      this.mark.appendChild(this.ring);
      this.svg.appendChild(this.mark);
      this.start = spec.start != null ? spec.start : null;
      var got = spec.v || spec.points ? Promise.resolve(spec) : fetch(spec.src, { credentials: "same-origin", headers: { Accept: "application/json" } }).then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return r.json();
      }).then(function (payload) {
        spec.v = payload.y;
        return spec;
      });
      this.loaded = got.then(function () {
        self.points = expand(spec);
        return self.points;
      }, function () {
        return self.points;
      });
    }
    return this.points;
  };

  /* Then: fn once the points are there. */
  Readout.prototype.then = function (fn) {
    this.data();
    var self = this;
    this.loaded.then(function () {
      fn.call(self, self.points);
    });
  };

  Readout.prototype.nearest = function (event) {
    var points = this.points, ctm = this.svg.getScreenCTM();
    if (!ctm || !points.length) return null;
    var pt = this.svg.createSVGPoint();
    pt.x = event.clientX;
    pt.y = event.clientY;
    var p = pt.matrixTransform(ctm.inverse()), best = null, bestD = Infinity, xy = this.spec.near === "xy";
    points.forEach(function (q, i) {
      var d = xy && q[1] != null ? Math.pow(q[0] - p.x, 2) + Math.pow(q[1] - p.y, 2) : Math.pow(q[0] - p.x, 2);
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    });
    return best;
  };

  Readout.prototype.show = function (i) {
    var points = this.data();
    if (!this.mark) return;
    if (i == null || !points[i]) {
      this.mark.setAttribute("display", "none");
      if (this.text) this.text.innerHTML = "&nbsp;";
      return;
    }
    var q = points[i];
    this.line.setAttribute("x1", q[0]);
    this.line.setAttribute("x2", q[0]);
    if (q[1] != null) {
      this.ring.setAttribute("cx", q[0]);
      this.ring.setAttribute("cy", q[1]);
      this.ring.removeAttribute("display");
    } else {
      this.ring.setAttribute("display", "none");
    }
    this.mark.removeAttribute("display");
    if (this.text) {
      this.text.hidden = false;
      this.text.textContent = q[2] + " · " + q[3];
    }
  };

  Readout.prototype.step = function (i) {
    var points = this.points;
    if (!points.length) return;
    this.cursor = Math.max(0, Math.min(points.length - 1, i));
    this.show(this.cursor);
    if (this.status) this.status.textContent = this.text ? this.text.textContent : points[this.cursor][2] + " · " + points[this.cursor][3];
  };

  Readout.prototype.act = function (i) {
    var q = this.points[i];
    if (!q) return;
    if (this.spec.href) {
      window.location.href = this.spec.href + encodeURIComponent(q[2]);
    } else if (this.spec.pick) {
      this.svg.dispatchEvent(new CustomEvent("climpact:readoutpick", { bubbles: true, detail: { when: q[2], index: i } }));
    }
  };

  Readout.prototype.wire = function () {
    var self = this, svg = this.svg;
    var described = svg.getAttribute("data-readout-keys");
    svg.setAttribute("tabindex", "0");
    svg.setAttribute("role", "group");
    svg.setAttribute("aria-roledescription", svg.getAttribute("data-readout-role") || "chart");
    if (described) svg.setAttribute("aria-describedby", described);
    svg.removeAttribute("focusable");
    svg.classList.add("is-readout");
    // The read-out's line is kept from the start, so the page does not move under it.
    if (this.text) this.text.hidden = false;
    var hover = false;
    svg.addEventListener("pointermove", function (event) {
      hover = true;
      if (self.data().length) self.show(self.nearest(event));
    });
    svg.addEventListener("pointerleave", function () {
      hover = false;
      self.show(doc.activeElement === svg ? self.cursor : null);
    });
    svg.addEventListener("click", function (event) {
      self.then(function () {
        var i = self.nearest(event);
        if (i == null) return;
        self.cursor = i;
        self.act(i);
      });
    });
    svg.addEventListener("focus", function () {
      self.then(function (points) {
        if (self.cursor == null) self.cursor = self.start != null ? self.start : points.length - 1;
        if (doc.activeElement === svg) self.show(self.cursor);
      });
    });
    svg.addEventListener("blur", function () {
      if (!hover) self.show(null);
    });
    svg.addEventListener("keydown", function (event) {
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      var spec = self.data() && self.spec;
      var move = { ArrowLeft: -1, ArrowRight: 1, Home: "first", End: "last" }[event.key];
      var act = (event.key === "Enter" || event.key === " ") && (spec.href || spec.pick);
      if (!move && !act) return;
      event.preventDefault();
      self.then(function (points) {
        var at = self.cursor == null ? points.length - 1 : self.cursor;
        if (act) self.act(at);
        else self.step(move === "first" ? 0 : move === "last" ? points.length - 1 : at + move);
      });
    });
  };

  function hydrate(scope) {
    Array.prototype.forEach.call((scope || doc).querySelectorAll("svg[data-readout]"), function (svg) {
      if (svg._readout) return;
      svg._readout = new Readout(svg);
      svg._readout.wire();
    });
  }

  if (doc.readyState === "loading") {
    doc.addEventListener("DOMContentLoaded", function () {
      hydrate(doc);
    });
  } else {
    hydrate(doc);
  }
  doc.addEventListener("htmx:load", function (event) {
    hydrate(event.target);
  });
  window.ClimpactReadout = { hydrate: hydrate };
})();
