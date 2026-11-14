/*
 * climpact-web interactive charts (#75). Hydrates every chart frame with a data URL
 * (components/chart_frame.html, <figure data-chart-src="...">) once it scrolls into view:
 * fetches the JSON (charts app), draws it with uPlot and wires up the toolbar (zoom, move,
 * show all, PNG and SVG export of the current view), the keyboard (+ - arrows 0), the hover
 * read-out, the table view and the CSV link. No build step, no other dependencies:
 * needs uPlot (vendor/uplot) loaded first and reads window.Climpact.chartPalette() (ui.js).
 *
 * Payload kinds (see charts/data.py): "daily" (a panel per kind of variable present:
 * temperature, DTR, precipitation; QC flags as rings, missing values as gaps) and "index"
 * (a line with the trend, or bars for SPI/SPEI).
 *
 * API (window.ClimpactCharts):
 *   hydrate(scope)            draw the charts inside scope (done on page load, htmx:load)
 *   get(figureOrId)           the chart of a frame (null before hydrate)
 *   focusDate(figureOrId, isoDate, {span: days})
 *                             daily charts: show span days (default 61) centred on the
 *                             date and mark it with a vertical line; loads the chart first
 *                             if it has not been drawn. Returns a Promise.
 * Event: a click on a daily chart (not a drag) dispatches "climpact:chartpick" on the
 * figure (bubbling), detail {date: "YYYY-MM-DD", index, checks: [QC check keys],
 * flagged}: the nearest flagged day within 8px, else the day under the pointer. The
 * clicked day is marked as by focusDate.
 */
(function () {
  "use strict";

  var doc = document;
  var DAY = 86400;
  var MAX_ROWS = 1000;
  var lang = doc.documentElement.lang || "en";
  var TEXT = {};
  var charts = [];

  try {
    TEXT = JSON.parse(doc.getElementById("climpact-chart-text").textContent);
  } catch (e) {
    TEXT = {};
  }

  function t(key, values) {
    return (TEXT[key] || key).replace(/\{(\w+)\}/g, function (m, k) {
      return values && k in values ? values[k] : m;
    });
  }

  var numberFormats = {};
  function num(v, digits) {
    if (v == null || v !== v) return "";
    var d = digits == null ? (Math.abs(v) < 10 ? 2 : 1) : digits;
    if (!numberFormats[d]) numberFormats[d] = new Intl.NumberFormat(lang, { maximumFractionDigits: d });
    return numberFormats[d].format(v);
  }

  var dayFormat = new Intl.DateTimeFormat(lang, { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
  var monthFormat = new Intl.DateTimeFormat(lang, { year: "numeric", month: "short", timeZone: "UTC" });

  function palette() {
    var p = window.Climpact && window.Climpact.chartPalette ? window.Climpact.chartPalette() : null;
    return p || { categorical: ["#2a78d6", "#eb6834"], roles: {}, surface: "#fff", text: "#000", text_muted: "#555" };
  }

  function colour(pal, token) {
    var name = token.replace(/^--chart-/, "");
    if (/^\d+$/.test(name)) return pal.categorical[+name - 1];
    return pal.roles[name] || getComputedStyle(doc.documentElement).getPropertyValue(token).trim();
  }

  function fontFamily() {
    return getComputedStyle(doc.body).fontFamily || "sans-serif";
  }

  /* ---- Payload -> model: x, panels of series, labels ---- */

  function dailyModel(p) {
    var n = p.days;
    var start = Date.parse(p.start + "T00:00:00Z") / 1000;
    var x = new Array(n);
    for (var i = 0; i < n; i++) x[i] = start + i * DAY;
    var byKey = {};
    p.series.forEach(function (s) {
      byKey[s.key] = s;
    });
    var flagValues = {};
    var flagInfo = {};
    var flagChecks = {};
    p.flags.points.forEach(function (f) {
      var s = byKey[f[1]];
      if (!s) return;
      if (!flagValues[f[1]]) flagValues[f[1]] = new Array(n).fill(null);
      flagValues[f[1]][f[0]] = s.values[f[0]];
      var text = s.short + ": " + (p.flags.checks[f[2]] || f[2]);
      var info = (flagInfo[f[0]] = flagInfo[f[0]] || []);
      if (info.indexOf(text) < 0) info.push(text);
      var checks = (flagChecks[f[0]] = flagChecks[f[0]] || []);
      if (checks.indexOf(f[2]) < 0) checks.push(f[2]);
    });
    function panel(key, label, keys, bars) {
      var series = keys.map(function (k) {
        var s = byKey[k];
        return { label: s.label, short: s.short, unit: s.unit, token: s.token, values: s.values, bars: bars };
      });
      keys.forEach(function (k) {
        if (flagValues[k]) {
          series.push({ label: p.flags.label, short: byKey[k].short, unit: byKey[k].unit, token: "--chart-flag", values: flagValues[k], flag: true });
        }
      });
      return { key: key, label: label, series: series };
    }
    var legend = p.series.map(function (s) {
      return { label: s.label, token: s.token };
    });
    if (p.flags.points.length) legend.push({ label: p.flags.label, token: "--chart-flag", ring: true });
    var panels = [];
    ["temperature", "dtr", "precipitation"].forEach(function (key) {
      var keys = p.series.filter(function (s) {
        return s.panel === key;
      }).map(function (s) {
        return s.key;
      });
      if (keys.length) panels.push(panel(key, p.panels[key], keys, key === "precipitation"));
    });
    return {
      kind: "daily",
      time: true,
      step: "day",
      x: x,
      minSpan: 7 * DAY,
      panels: panels,
      weights: panels.length === 2 ? [0.6, 0.4] : panels.map(function () {
        return 1 / panels.length;
      }),
      legend: legend,
      flagInfo: flagInfo,
      flagChecks: flagChecks,
      label: function (v) {
        return dayFormat.format(new Date(v * 1000));
      }
    };
  }

  function indexModel(p) {
    var x = p.x;
    var y = p.y;
    var series = [];
    var legend = [];
    if (p.bars) {
      series.push({ label: t("wet"), short: p.label, unit: p.units, token: "--chart-1", bars: true, values: y.map(function (v) { return v != null && v >= 0 ? v : null; }) });
      series.push({ label: t("dry"), short: p.label, unit: p.units, token: "--chart-2", bars: true, values: y.map(function (v) { return v != null && v < 0 ? v : null; }) });
      legend.push({ label: t("wet"), token: "--chart-1", box: true }, { label: t("dry"), token: "--chart-2", box: true });
    } else {
      series.push({ label: p.label, short: p.label, unit: p.units, token: "--chart-1", values: y, markers: p.step !== "month" && x.length <= 200, thin: p.step === "month" });
      legend.push({ label: p.label, token: "--chart-1" });
    }
    if (p.trend) {
      var tr = p.trend;
      series.push({ label: tr.label, short: t("trend"), unit: p.units, token: "--chart-trend", trend: true, values: x.map(function (v, i) { return tr.intercept + tr.slope * i; }) });
      legend.push({ label: tr.label, token: "--chart-trend", dash: true });
    }
    var spacing = p.step === "month" ? 1 / 12 : 1;
    return {
      kind: "index",
      time: false,
      step: p.step,
      x: x,
      minSpan: spacing * 4,
      panels: [{ key: "index", label: p.axis || p.units, series: series, zero: p.bars }],
      weights: [1],
      legend: legend,
      dates: p.dates,
      label: function (v) {
        if (p.step === "month") {
          var year = Math.floor(v);
          return monthFormat.format(new Date(Date.UTC(year, Math.round((v - year) * 12 - 0.5))));
        }
        if (p.step === "day") return t("day") + " " + Math.round(v);
        return String(Math.round(v));
      }
    };
  }

  /* ---- uPlot options ---- */

  function uSeries(s, pal) {
    var c = colour(pal, s.token);
    var out = { label: s.label, stroke: c, width: s.thin ? 1 : 1.5, spanGaps: !!s.trend, points: { show: false } };
    if (s.bars) {
      out.paths = uPlot.paths.bars({ size: [0.9, 40, 1], align: 0 });
      out.fill = c;
      out.width = 0;
    }
    if (s.trend) {
      out.dash = [6, 4];
      out.width = 2;
    }
    if (s.markers) out.points = { show: true, size: 6, width: 1.5, fill: pal.surface, stroke: c };
    if (s.flag) {
      out.paths = function () {
        return null;
      };
      out.points = { show: true, size: 9, width: 1.5, fill: "transparent", stroke: c, space: 0 };
    }
    return out;
  }

  function monthNames() {
    var long = [], short = [], wlong = [], wshort = [];
    for (var m = 0; m < 12; m++) {
      var d = new Date(Date.UTC(2001, m, 1));
      long.push(d.toLocaleString(lang, { month: "long", timeZone: "UTC" }));
      short.push(d.toLocaleString(lang, { month: "short", timeZone: "UTC" }));
    }
    for (var w = 0; w < 7; w++) {
      var day = new Date(Date.UTC(2001, 0, 7 + w));
      wlong.push(day.toLocaleString(lang, { weekday: "long", timeZone: "UTC" }));
      wshort.push(day.toLocaleString(lang, { weekday: "short", timeZone: "UTC" }));
    }
    return { MMMM: long, MMM: short, WWWW: wlong, WWW: wshort };
  }

  function plotOptions(chart, panel, index, width, height) {
    var pal = palette();
    var model = chart.model;
    var font = "12px " + fontFamily();
    var last = index === model.panels.length - 1;
    var grid = { stroke: pal.roles.grid, width: 1 };
    var xAxis = { stroke: pal.text_muted, grid: grid, ticks: { stroke: pal.roles.grid }, font: font, size: last ? (model.time ? 50 : 36) : 8 };
    if (!last) {
      xAxis.values = function (u, splits) {
        return splits.map(function () {
          return "";
        });
      };
    } else if (!model.time) {
      xAxis.incrs = model.step === "day" ? [1, 2, 5, 10, 15, 30, 60, 90] : [1 / 12, 0.25, 0.5, 1, 2, 5, 10, 20, 25, 50];
      xAxis.values = function (u, splits) {
        return splits.map(function (v) {
          if (model.step === "day") return String(Math.round(v));
          if (Math.abs(v - Math.round(v)) < 1e-6) return String(Math.round(v));
          return model.step === "month" ? monthFormat.format(new Date(Date.UTC(Math.floor(v), Math.round((v - Math.floor(v)) * 12)))) : "";
        });
      };
    }
    var opts = {
      width: width,
      height: height,
      legend: { show: false },
      cursor: {
        sync: { key: chart.id },
        drag: { x: true, y: false },
        points: { size: 7 }
      },
      scales: {
        x: { time: model.time },
        y: {
          range: function (u, min, max) {
            if (min == null) return [0, 1];
            if (panel.zero || panel.key === "precipitation") {
              min = Math.min(0, min);
              max = Math.max(0, max);
            }
            return uPlot.rangeNum(min, max, 0.08, true);
          }
        }
      },
      axes: [
        xAxis,
        { stroke: pal.text_muted, grid: grid, ticks: { stroke: pal.roles.grid }, font: font, labelFont: font, label: panel.label, labelSize: 18, size: 52 }
      ],
      series: [{}].concat(panel.series.map(function (s) {
        return uSeries(s, pal);
      })),
      hooks: {
        setScale: [
          function (u, key) {
            if (key === "x") chart.scaled(u);
          }
        ],
        setCursor: [
          function (u) {
            chart.hover(u.cursor.idx);
          }
        ],
        draw: [
          function (u) {
            if (chart.marked == null) return;
            var pos = u.valToPos(chart.marked, "x", true);
            if (pos < u.bbox.left || pos > u.bbox.left + u.bbox.width) return;
            var ctx = u.ctx, r = u.bbox;
            ctx.save();
            ctx.strokeStyle = colour(pal, "--chart-flag");
            ctx.lineWidth = 2 * (window.devicePixelRatio || 1);
            ctx.setLineDash([4 * (window.devicePixelRatio || 1), 3 * (window.devicePixelRatio || 1)]);
            ctx.beginPath();
            ctx.moveTo(pos, r.top);
            ctx.lineTo(pos, r.top + r.height);
            ctx.stroke();
            ctx.restore();
          }
        ],
        ready: [
          function (u) {
            if (model.kind === "daily") chart.listen(u);
          }
        ]
      }
    };
    if (model.time) {
      var names = monthNames();
      opts.tzDate = function (ts) {
        return uPlot.tzDate(new Date(ts * 1000), "Etc/UTC");
      };
      opts.fmtDate = function (tpl) {
        return uPlot.fmtDate(tpl, names);
      };
    }
    return opts;
  }

  /* ---- A chart ---- */

  function Chart(el) {
    this.el = el;
    this.id = el.id;
    this.plotEl = el.querySelector("[data-chart-plot]");
    this.status = el.querySelector("[data-chart-status]");
    this.readout = el.querySelector("[data-chart-readout]");
    this.plots = [];
    this.syncing = false;
  }

  Chart.prototype.load = function () {
    var self = this;
    this.requested = true;
    fetch(this.el.getAttribute("data-chart-src"), { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return r.json();
      })
      .then(function (payload) {
        if (!window.uPlot) throw new Error("uPlot");
        self.payload = payload;
        self.model = payload.kind === "daily" ? dailyModel(payload) : indexModel(payload);
        self.fill();
        self.draw();
        self.wire();
        self.loaded = true;
        (self.waiting || []).forEach(function (resolve) {
          resolve(self);
        });
        self.waiting = null;
      })
      .catch(function () {
        self.plotEl.innerHTML = "";
        var p = doc.createElement("p");
        p.className = "chart__error";
        p.textContent = t("loadError");
        self.plotEl.appendChild(p);
        self.plotEl.removeAttribute("tabindex");
      });
  };

  Chart.prototype.fill = function () {
    var el = this.el, p = this.payload, model = this.model;
    var summary = el.querySelector("[data-chart-summary]");
    if (summary && !summary.textContent.trim()) summary.textContent = p.summary || "";
    var csv = el.querySelector("[data-chart-csv]");
    if (csv && csv.hidden && p.csv) {
      csv.href = p.csv;
      csv.hidden = false;
    }
    var legend = el.querySelector("[data-chart-legend]");
    if (legend) {
      legend.innerHTML = "";
      model.legend.forEach(function (item) {
        var li = doc.createElement("li");
        var sw = doc.createElement("span");
        sw.className = "chart__swatch" + (item.ring ? " chart__swatch--ring" : "") + (item.dash ? " chart__swatch--dash" : "") + (item.box ? " chart__swatch--box" : "");
        sw.style.setProperty("--swatch", "var(" + item.token + ")");
        sw.setAttribute("aria-hidden", "true");
        li.appendChild(sw);
        li.appendChild(doc.createTextNode(item.label));
        legend.appendChild(li);
      });
      legend.hidden = false;
    }
    var toolbar = el.querySelector("[data-chart-toolbar]");
    if (toolbar) toolbar.hidden = false;
    var table = el.querySelector("[data-chart-table]");
    if (table) table.hidden = false;
  };

  Chart.prototype.size = function () {
    var style = getComputedStyle(this.plotEl);
    var total = parseFloat(style.minHeight) || 256;
    return { width: Math.max(200, this.plotEl.clientWidth), height: total };
  };

  Chart.prototype.draw = function (range) {
    var self = this, model = this.model;
    this.plots.forEach(function (u) {
      u.destroy();
    });
    this.plots = [];
    this.plotEl.innerHTML = "";
    this.plotEl.setAttribute("dir", "ltr");
    var size = this.size();
    model.panels.forEach(function (panel, i) {
      var box = doc.createElement("div");
      box.className = "chart__panel";
      self.plotEl.appendChild(box);
      var data = [model.x].concat(panel.series.map(function (s) {
        return s.values;
      }));
      var h = Math.round(size.height * model.weights[i]);
      self.plots.push(new uPlot(plotOptions(self, panel, i, size.width, h), data, box));
    });
    if (range) this.setRange(range[0], range[1]);
  };

  Chart.prototype.range = function () {
    var s = this.plots[0].scales.x;
    return [s.min, s.max];
  };

  Chart.prototype.full = function () {
    var x = this.model.x;
    return [x[0], x[x.length - 1]];
  };

  Chart.prototype.setRange = function (min, max) {
    var full = this.full();
    var span = Math.max(max - min, Math.min(this.model.minSpan, full[1] - full[0]));
    if (span >= full[1] - full[0]) {
      min = full[0];
      max = full[1];
    } else {
      min = Math.max(full[0], Math.min(min, full[1] - span));
      max = min + span;
    }
    this.plots[0].setScale("x", { min: min, max: max });
  };

  Chart.prototype.scaled = function (u) {
    var self = this;
    if (this.syncing) return;
    this.syncing = true;
    var s = u.scales.x;
    this.plots.forEach(function (other) {
      if (other !== u) other.setScale("x", { min: s.min, max: s.max });
    });
    this.syncing = false;
    clearTimeout(this.announceTimer);
    this.announceTimer = setTimeout(function () {
      self.announce();
      self.renderTable();
    }, 350);
  };

  Chart.prototype.announce = function () {
    if (!this.status || !this.el.contains(doc.activeElement)) return;
    var r = this.range(), f = this.full();
    this.status.textContent = r[0] <= f[0] && r[1] >= f[1] ? t("all") : t("showing", { from: this.model.label(r[0]), to: this.model.label(r[1]) });
  };

  Chart.prototype.action = function (name) {
    var r = this.range(), span = r[1] - r[0], mid = (r[0] + r[1]) / 2;
    if (name === "zoom-in") this.setRange(mid - span / 4, mid + span / 4);
    else if (name === "zoom-out") this.setRange(mid - span, mid + span);
    else if (name === "left") this.setRange(r[0] - span / 4, r[1] - span / 4);
    else if (name === "right") this.setRange(r[0] + span / 4, r[1] + span / 4);
    else if (name === "reset") this.setRange(this.full()[0], this.full()[1]);
    else if (name === "png") this.exportPng();
    else if (name === "svg") this.exportSvg();
  };

  Chart.prototype.hover = function (idx) {
    if (!this.readout) return;
    if (idx == null) {
      this.readout.innerHTML = "&nbsp;";
      return;
    }
    var model = this.model, parts = [model.label(model.x[idx])];
    if (model.dates && model.dates[idx]) parts[0] += " (" + model.dates[idx] + ")";
    model.panels.forEach(function (panel) {
      panel.series.forEach(function (s) {
        if (s.flag) return;
        var v = s.values[idx];
        if (s.bars && v == null && model.kind === "index") return;
        var unit = s.unit ? " " + s.unit : "";
        parts.push(s.short + " " + (v == null ? t("missing") : num(v) + unit));
      });
    });
    if (model.flagInfo && model.flagInfo[idx]) parts.push(t("flagged") + ": " + model.flagInfo[idx].join(", "));
    this.readout.textContent = parts.join(" · ");
  };

  Chart.prototype.visible = function () {
    var x = this.model.x, r = this.range(), lo = 0, hi = x.length - 1;
    while (lo < x.length && x[lo] < r[0]) lo++;
    while (hi >= 0 && x[hi] > r[1]) hi--;
    return [lo, hi];
  };

  /* ---- Picking and focusing a date (daily charts) ---- */

  function isoDay(seconds) {
    return new Date(seconds * 1000).toISOString().slice(0, 10);
  }

  Chart.prototype.ready = function () {
    var self = this;
    if (this.loaded) return Promise.resolve(this);
    return new Promise(function (resolve) {
      (self.waiting = self.waiting || []).push(resolve);
      if (!self.requested) {
        self.requested = true;
        if (observer) observer.unobserve(self.el);
        self.load();
      }
    });
  };

  Chart.prototype.mark = function (x) {
    this.marked = x;
    this.plots.forEach(function (u) {
      u.redraw(false);
    });
  };

  Chart.prototype.focusDate = function (iso, span) {
    var x = Date.parse(iso + "T00:00:00Z") / 1000;
    var half = Math.floor((span || 61) / 2) * DAY;
    this.setRange(x - half, x + half);
    this.mark(x);
    var idx = Math.round((x - this.model.x[0]) / DAY);
    if (idx >= 0 && idx < this.model.x.length) this.hover(idx);
    if (this.status) this.status.textContent = t("showing", { from: this.model.label(x - half), to: this.model.label(x + half) });
  };

  Chart.prototype.listen = function (u) {
    var self = this, downX = null;
    u.over.addEventListener("mousedown", function (e) {
      downX = e.clientX;
    });
    u.over.addEventListener("click", function (e) {
      if (downX == null || Math.abs(e.clientX - downX) > 3 || u.cursor.left == null) return;
      var model = self.model, left = u.cursor.left, best = null;
      var lo = u.posToIdx(left - 8), hi = u.posToIdx(left + 8);
      for (var i = Math.max(0, lo); i <= Math.min(model.x.length - 1, hi); i++) {
        if (model.flagChecks[i] && (best == null || Math.abs(u.valToPos(model.x[i], "x") - left) < Math.abs(u.valToPos(model.x[best], "x") - left))) best = i;
      }
      var idx = best != null ? best : u.cursor.idx;
      if (idx == null) return;
      self.mark(model.x[idx]);
      self.el.dispatchEvent(new CustomEvent("climpact:chartpick", { bubbles: true, detail: { date: isoDay(model.x[idx]), index: idx, checks: model.flagChecks[idx] || [], flagged: best != null } }));
    });
  };

  /* ---- Table view: the values in view ---- */

  Chart.prototype.renderTable = function () {
    var details = this.el.querySelector("[data-chart-table]");
    if (!details || !details.open || !this.model) return;
    var body = details.querySelector("[data-chart-table-body]");
    var model = this.model, v = this.visible(), count = v[1] - v[0] + 1;
    body.innerHTML = "";
    if (count > MAX_ROWS) {
      var p = doc.createElement("p");
      p.textContent = t("tooMany", { n: num(count, 0), max: num(MAX_ROWS, 0) });
      body.appendChild(p);
      return;
    }
    var columns = [];
    model.panels.forEach(function (panel) {
      panel.series.forEach(function (s) {
        if (!s.flag && !(s.bars && model.kind === "index")) columns.push(s);
      });
    });
    var wrap = doc.createElement("div");
    wrap.className = "table-wrap";
    wrap.setAttribute("role", "region");
    wrap.setAttribute("tabindex", "0");
    var table = doc.createElement("table");
    table.className = "table";
    var caption = table.createCaption();
    caption.textContent = t("tableCaption", { from: model.label(model.x[v[0]]), to: model.label(model.x[v[1]]) });
    wrap.setAttribute("aria-label", caption.textContent);
    var head = "<tr><th scope='col'>" + esc(t(model.step === "day" && model.time ? "date" : model.step)) + "</th>";
    if (model.kind === "index" && this.payload.bars) head += "<th scope='col' class='num'>" + esc(this.payload.label) + "</th>";
    columns.forEach(function (s) {
      head += "<th scope='col' class='num'>" + esc(s.trend ? t("trend") : s.label) + (s.unit ? " (" + esc(s.unit) + ")" : "") + "</th>";
    });
    if (model.dates) head += "<th scope='col'>" + esc(t("dateOfEvent")) + "</th>";
    if (model.flagInfo) head += "<th scope='col'>" + esc(t("flagged")) + "</th>";
    var rows = [head + "</tr>"];
    for (var i = v[0]; i <= v[1]; i++) {
      var row = "<tr><th scope='row'>" + esc(model.label(model.x[i])) + "</th>";
      if (model.kind === "index" && this.payload.bars) row += "<td class='num'>" + cell(this.payload.y[i]) + "</td>";
      columns.forEach(function (s) {
        row += "<td class='num'>" + cell(s.values[i], s.trend ? 3 : null) + "</td>";
      });
      if (model.dates) row += "<td>" + esc(model.dates[i] || "") + "</td>";
      if (model.flagInfo) row += "<td>" + esc((model.flagInfo[i] || []).join(", ")) + "</td>";
      rows.push(row + "</tr>");
    }
    table.insertAdjacentHTML("beforeend", "<thead>" + rows[0] + "</thead><tbody>" + rows.slice(1).join("") + "</tbody>");
    wrap.appendChild(table);
    body.appendChild(wrap);
  };

  function cell(v, digits) {
    return v == null ? "<span class='muted'>" + esc(t("missing")) + "</span>" : esc(num(v, digits == null ? 3 : digits));
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /* ---- Export ---- */

  Chart.prototype.fileName = function (ext) {
    var name = (this.payload.name || this.payload.title || "chart").replace(/[^\w.-]+/g, "_");
    return name + "." + ext;
  };

  Chart.prototype.heading = function () {
    var r = this.range();
    var title = this.el.querySelector(".chart__title");
    return [(title ? title.textContent : this.payload.title).trim(), this.model.label(r[0]) + " – " + this.model.label(r[1])];
  };

  function save(blob, name) {
    var a = doc.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    doc.body.appendChild(a);
    a.click();
    setTimeout(function () {
      URL.revokeObjectURL(a.href);
      a.remove();
    }, 1000);
  }

  Chart.prototype.exportPng = function () {
    var pal = palette(), canvases = this.plots.map(function (u) {
      return u.ctx.canvas;
    });
    var ratio = canvases[0].width / this.plots[0].width || 1;
    var pad = 16 * ratio, head = 64 * ratio, foot = 28 * ratio;
    var width = canvases[0].width + 2 * pad;
    var height = canvases.reduce(function (h, c) {
      return h + c.height;
    }, 0) + head + foot;
    var out = doc.createElement("canvas");
    out.width = width;
    out.height = height;
    var ctx = out.getContext("2d");
    var family = fontFamily(), lines = this.heading();
    ctx.fillStyle = pal.surface;
    ctx.fillRect(0, 0, width, height);
    ctx.fillStyle = pal.text;
    ctx.font = "600 " + 16 * ratio + "px " + family;
    ctx.fillText(lines[0], pad, pad + 14 * ratio);
    ctx.fillStyle = pal.text_muted;
    ctx.font = 13 * ratio + "px " + family;
    ctx.fillText(lines[1], pad, pad + 36 * ratio);
    var y = head;
    canvases.forEach(function (c) {
      ctx.drawImage(c, pad, y);
      y += c.height;
    });
    var x = pad;
    ctx.font = 12 * ratio + "px " + family;
    this.model.legend.forEach(function (item) {
      var c = colour(pal, item.token);
      ctx.fillStyle = c;
      ctx.strokeStyle = c;
      ctx.lineWidth = 1.5 * ratio;
      if (item.ring) {
        ctx.beginPath();
        ctx.arc(x + 7 * ratio, y + 12 * ratio, 4.5 * ratio, 0, 2 * Math.PI);
        ctx.stroke();
      } else if (item.dash) {
        ctx.fillRect(x, y + 10 * ratio, 6 * ratio, 3 * ratio);
        ctx.fillRect(x + 9 * ratio, y + 10 * ratio, 5 * ratio, 3 * ratio);
      } else {
        ctx.fillRect(x, y + 10 * ratio, 14 * ratio, item.box ? 10 * ratio : 3 * ratio);
      }
      ctx.fillStyle = pal.text_muted;
      ctx.fillText(item.label, x + 20 * ratio, y + 16 * ratio);
      x += ctx.measureText(item.label).width + 40 * ratio;
    });
    var name = this.fileName("png");
    out.toBlob(function (blob) {
      save(blob, name);
    });
  };

  function niceTicks(min, max, count) {
    var step = Math.pow(10, Math.floor(Math.log10((max - min) / count || 1)));
    var err = (max - min) / count / step;
    step *= err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1;
    var out = [];
    for (var v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) out.push(+v.toPrecision(12));
    return out;
  }

  function attr(o) {
    return Object.keys(o).map(function (k) {
      return k + '="' + esc(o[k]) + '"';
    }).join(" ");
  }

  Chart.prototype.exportSvg = function () {
    var pal = palette(), model = this.model, vis = this.visible();
    var family = fontFamily(), lines = this.heading();
    var width = this.plots[0].width, head = 64, pad = 16, y0 = head;
    var parts = [];
    var self = this;
    this.plots.forEach(function (u, pi) {
      var ratio = u.ctx.canvas.width / u.width || 1;
      var bb = { left: u.bbox.left / ratio, top: u.bbox.top / ratio, width: u.bbox.width / ratio, height: u.bbox.height / ratio };
      var panel = model.panels[pi];
      var g = ['<g transform="translate(' + pad + "," + y0 + ')">'];
      var px = function (v) {
        return +(bb.left + u.valToPos(v, "x")).toFixed(1);
      };
      var py = function (v) {
        return +(bb.top + u.valToPos(v, "y")).toFixed(1);
      };
      var axisX = u.axes[0], axisY = u.axes[1];
      var xs = axisX._splits || niceTicks(u.scales.x.min, u.scales.x.max, 6);
      var ys = axisY._splits || niceTicks(u.scales.y.min, u.scales.y.max, 5);
      var xl = axisX._values || xs.map(model.label);
      var yl = axisY._values || ys.map(function (v) {
        return num(v);
      });
      ys.forEach(function (v, i) {
        var yy = py(v);
        g.push("<line " + attr({ x1: bb.left, x2: bb.left + bb.width, y1: yy, y2: yy, stroke: pal.roles.grid }) + "/>");
        g.push("<text " + attr({ x: bb.left - 6, y: yy, "text-anchor": "end", "dominant-baseline": "middle" }) + ">" + esc(yl[i]) + "</text>");
      });
      xs.forEach(function (v, i) {
        var xx = px(v);
        if (xx < bb.left - 0.5 || xx > bb.left + bb.width + 0.5) return;
        g.push("<line " + attr({ x1: xx, x2: xx, y1: bb.top, y2: bb.top + bb.height, stroke: pal.roles.grid }) + "/>");
        if (pi === model.panels.length - 1 && xl[i]) g.push("<text " + attr({ x: xx, y: bb.top + bb.height + 16, "text-anchor": "middle" }) + ">" + esc(xl[i]) + "</text>");
      });
      g.push("<text " + attr({ transform: "translate(12," + (bb.top + bb.height / 2) + ") rotate(-90)", "text-anchor": "middle" }) + ">" + esc(panel.label) + "</text>");
      g.push('<g clip-path="url(#clip' + pi + ')">');
      panel.series.forEach(function (s) {
        g.push(svgSeries(s, model.x, vis, px, py, colour(pal, s.token), pal, bb));
      });
      g.push("</g></g>");
      parts.push('<clipPath id="clip' + pi + '"><rect ' + attr({ x: bb.left, y: bb.top, width: bb.width, height: bb.height }) + "/></clipPath>");
      parts.push(g.join(""));
      y0 += u.height;
    });
    var x = pad, legend = [];
    model.legend.forEach(function (item) {
      var c = colour(pal, item.token);
      legend.push(item.ring ? "<circle " + attr({ cx: x + 7, cy: y0 + 12, r: 4.5, fill: "none", stroke: c, "stroke-width": 1.5 }) + "/>" : item.dash ? "<line " + attr({ x1: x, x2: x + 14, y1: y0 + 11.5, y2: y0 + 11.5, stroke: c, "stroke-width": 3, "stroke-dasharray": "6 3" }) + "/>" : "<rect " + attr({ x: x, y: y0 + 10, width: 14, height: item.box ? 10 : 3, fill: c }) + "/>");
      legend.push("<text " + attr({ x: x + 20, y: y0 + 16, fill: pal.text_muted }) + ">" + esc(item.label) + "</text>");
      x += item.label.length * 6.5 + 40;
    });
    var total = y0 + 28;
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" ' + attr({ width: width + 2 * pad, height: total, viewBox: "0 0 " + (width + 2 * pad) + " " + total, "font-family": family, "font-size": 12, fill: pal.text_muted }) + ">" +
      "<title>" + esc(lines[0]) + "</title><desc>" + esc(self.payload.summary || "") + "</desc>" +
      "<rect " + attr({ width: "100%", height: "100%", fill: pal.surface }) + "/>" +
      "<text " + attr({ x: pad, y: pad + 14, "font-size": 16, "font-weight": 600, fill: pal.text }) + ">" + esc(lines[0]) + "</text>" +
      "<text " + attr({ x: pad, y: pad + 36, "font-size": 13 }) + ">" + esc(lines[1]) + "</text>" +
      parts.join("") + legend.join("") + "</svg>";
    save(new Blob([svg], { type: "image/svg+xml" }), this.fileName("svg"));
  };

  /* One series as SVG, over the visible points. Long series are reduced to the lowest and
     highest value of each pixel column (the look of the canvas at that width). */
  function svgSeries(s, x, vis, px, py, c, pal, bb) {
    var i, v, cols = {}, out = [];
    if (s.flag || s.markers) {
      for (i = vis[0]; i <= vis[1]; i++) {
        v = s.values[i];
        if (v != null) out.push("<circle " + attr({ cx: px(x[i]), cy: py(v), r: s.flag ? 4 : 2.5, fill: s.flag ? "none" : pal.surface, stroke: c, "stroke-width": 1.5 }) + "/>");
      }
      if (s.flag) return out.join("");
    }
    if (s.bars) {
      var zero = py(0), w = Math.max(1, bb.width / Math.max(1, vis[1] - vis[0] + 1) * 0.9);
      for (i = vis[0]; i <= vis[1]; i++) {
        v = s.values[i];
        if (v == null) continue;
        var col = Math.round(px(x[i]));
        if (w <= 1.5) {
          cols[col] = v > 0 ? Math.max(cols[col] || 0, v) : Math.min(cols[col] || 0, v);
        } else {
          out.push("<rect " + attr({ x: +(px(x[i]) - w / 2).toFixed(1), y: Math.min(zero, py(v)), width: +w.toFixed(1), height: +Math.abs(py(v) - zero).toFixed(1), fill: c }) + "/>");
        }
      }
      Object.keys(cols).forEach(function (k) {
        var y = py(cols[k]);
        out.push("<rect " + attr({ x: k, y: Math.min(zero, y), width: 1, height: +Math.abs(y - zero).toFixed(1), fill: c }) + "/>");
      });
      return out.join("");
    }
    var d = [], pen = false, many = vis[1] - vis[0] > 2 * bb.width, lastCol = null, lo, hi;
    function flush() {
      if (lastCol == null) return;
      d.push((pen ? "L" : "M") + lastCol + " " + py(hi));
      pen = true;
      if (lo !== hi) d.push("L" + lastCol + " " + py(lo));
    }
    for (i = vis[0]; i <= vis[1]; i++) {
      v = s.values[i];
      if (v == null) {
        flush();
        lastCol = null;
        pen = false;
        continue;
      }
      if (!many) {
        d.push((pen ? "L" : "M") + px(x[i]) + " " + py(v));
        pen = true;
        continue;
      }
      var colX = Math.round(px(x[i]));
      if (colX !== lastCol) {
        flush();
        lastCol = colX;
        lo = hi = v;
      } else {
        lo = Math.min(lo, v);
        hi = Math.max(hi, v);
      }
    }
    flush();
    out.unshift("<path " + attr({ d: d.join(""), fill: "none", stroke: c, "stroke-width": s.trend ? 2 : s.thin ? 1 : 1.5, "stroke-dasharray": s.trend ? "6 4" : "none", "stroke-linejoin": "round" }) + "/>");
    return out.join("");
  }

  /* ---- Events ---- */

  Chart.prototype.wire = function () {
    var self = this, el = this.el;
    if (el.hasAttribute("data-chart-wired")) return;
    el.setAttribute("data-chart-wired", "");
    el.addEventListener("click", function (event) {
      var button = event.target.closest("[data-chart-action]");
      if (button && el.contains(button)) self.action(button.getAttribute("data-chart-action"));
    });
    this.plotEl.addEventListener("keydown", function (event) {
      var keys = { "+": "zoom-in", "=": "zoom-in", "-": "zoom-out", _: "zoom-out", ArrowLeft: "left", ArrowRight: "right", 0: "reset", Home: "reset" };
      var name = keys[event.key];
      if (!name || event.altKey || event.ctrlKey || event.metaKey) return;
      event.preventDefault();
      self.action(name);
    });
    var details = el.querySelector("[data-chart-table]");
    if (details) {
      details.addEventListener("toggle", function () {
        self.renderTable();
      });
    }
    if (window.ResizeObserver) {
      var width = this.plotEl.clientWidth;
      new ResizeObserver(function () {
        var w = self.plotEl.clientWidth;
        if (Math.abs(w - width) < 2 || !self.plots.length) return;
        width = w;
        var size = self.size();
        self.plots.forEach(function (u, i) {
          u.setSize({ width: Math.max(200, w), height: Math.round(size.height * self.model.weights[i]) });
        });
      }).observe(this.plotEl);
    }
  };

  var observer = window.IntersectionObserver
    ? new IntersectionObserver(
        function (entries) {
          entries.forEach(function (entry) {
            if (!entry.isIntersecting) return;
            observer.unobserve(entry.target);
            entry.target._chart.load();
          });
        },
        { rootMargin: "200px 0px" }
      )
    : null;

  function hydrate(scope) {
    Array.prototype.forEach.call((scope || doc).querySelectorAll("[data-chart-src]"), function (el) {
      if (el._chart) return;
      el._chart = new Chart(el);
      charts.push(el._chart);
      if (observer) observer.observe(el);
      else el._chart.load();
    });
  }

  doc.addEventListener("climpact:themechange", function () {
    charts = charts.filter(function (c) {
      return doc.body.contains(c.el);
    });
    charts.forEach(function (c) {
      if (c.plots.length) c.draw(c.range());
    });
  });

  function chartOf(target) {
    var el = typeof target === "string" ? doc.getElementById(target) : target;
    if (el && !el._chart) hydrate(el.parentNode || doc);
    return el && el._chart ? el._chart : null;
  }

  window.ClimpactCharts = {
    hydrate: hydrate,
    get: chartOf,
    focusDate: function (target, iso, options) {
      var chart = chartOf(target);
      if (!chart) return Promise.reject(new Error("no chart"));
      return chart.ready().then(function (c) {
        if (c.model && c.model.kind === "daily") c.focusDate(iso, options && options.span);
        return c;
      });
    }
  };
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
})();
