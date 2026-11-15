/*
 * climpact-web UI behaviour (#71). Progressive enhancement only: every page works without
 * this file, which adds the theme toggle, tabs, drag and drop on file inputs, dialogs and
 * toasts, announcements of polled progress and focus kept across htmx swaps (#83). Runs
 * on page load and again on content htmx swaps in. No dependencies.
 *
 * window.Climpact:
 *   toast(message, kind)   show a toast; kind is "info", "success", "warning" or "error".
 *                          A server response can raise one with the header
 *                          HX-Trigger: {"toast": {"message": "...", "kind": "success"}}
 *   chartPalette()         the current theme's --chart-* colours, for the charts (#75)
 *   setTheme(theme)        "light", "dark" or "" (follow the system)
 * The document receives a "climpact:themechange" event when the theme changes.
 */
(function () {
  "use strict";

  var doc = document;
  var root = doc.documentElement;
  var THEME_KEY = "climpact-theme";
  var darkQuery = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

  function each(scope, selector, fn) {
    Array.prototype.forEach.call(scope.querySelectorAll(selector), fn);
  }

  function enhanceOnce(el, flag) {
    if (el.hasAttribute("data-enhanced-" + flag)) return false;
    el.setAttribute("data-enhanced-" + flag, "");
    return true;
  }

  /* ---- Theme ---- */
  function storedTheme() {
    try {
      return localStorage.getItem(THEME_KEY) || "";
    } catch (e) {
      return "";
    }
  }

  /* The stylesheet's dark tokens follow data-theme on <html>: "dark", "light", or none for
     the OS preference (#118). */
  function setTheme(theme) {
    if (theme) root.setAttribute("data-theme", theme);
    else root.removeAttribute("data-theme");
    try {
      if (theme) localStorage.setItem(THEME_KEY, theme);
      else localStorage.removeItem(THEME_KEY);
    } catch (e) {
      /* private browsing: the choice lasts for this page only */
    }
    each(doc, "[data-theme-value]", function (button) {
      button.setAttribute("aria-pressed", String(button.getAttribute("data-theme-value") === theme));
    });
    doc.dispatchEvent(new CustomEvent("climpact:themechange", { detail: { theme: currentTheme() } }));
  }

  function currentTheme() {
    var chosen = root.getAttribute("data-theme");
    if (chosen) return chosen;
    return darkQuery && darkQuery.matches ? "dark" : "light";
  }

  function initThemeToggle(scope) {
    each(scope, "[data-theme-toggle]", function (group) {
      if (!enhanceOnce(group, "theme")) return;
      var theme = storedTheme();
      each(group, "[data-theme-value]", function (button) {
        button.setAttribute("aria-pressed", String(button.getAttribute("data-theme-value") === theme));
        button.addEventListener("click", function () {
          setTheme(button.getAttribute("data-theme-value"));
        });
      });
      group.hidden = false;
    });
  }

  if (darkQuery && darkQuery.addEventListener) {
    darkQuery.addEventListener("change", function () {
      if (!root.getAttribute("data-theme")) {
        doc.dispatchEvent(new CustomEvent("climpact:themechange", { detail: { theme: currentTheme() } }));
      }
    });
  }

  function chartPalette() {
    var style = getComputedStyle(root);
    var read = function (name) {
      return style.getPropertyValue("--chart-" + name).trim();
    };
    var list = function (prefix, n) {
      var out = [];
      for (var i = 1; i <= n; i++) out.push(read(prefix + i));
      return out;
    };
    var roles = {};
    ["tmax", "tmin", "prcp", "trend", "trend-band", "flag", "grid", "axis"].forEach(
      function (role) {
        roles[role] = read(role);
      }
    );
    return {
      theme: currentTheme(),
      categorical: list("", 8),
      roles: roles,
      sequential: list("seq-", 5),
      diverging: list("div-", 7),
      surface: style.getPropertyValue("--color-surface").trim(),
      text: style.getPropertyValue("--color-text").trim(),
      text_muted: style.getPropertyValue("--color-text-muted").trim()
    };
  }

  /* ---- Tabs: links to panels become an ARIA tablist ---- */
  function initTabs(scope) {
    each(scope, "[data-tabs]", function (container) {
      if (!enhanceOnce(container, "tabs")) return;
      var list = container.querySelector(".tabs__list");
      var tabs = Array.prototype.slice.call(list.querySelectorAll(".tabs__tab"));
      var panels = tabs.map(function (tab) {
        return doc.getElementById(tab.getAttribute("href").slice(1));
      });
      list.setAttribute("role", "tablist");
      tabs.forEach(function (tab, i) {
        tab.parentNode.setAttribute("role", "presentation");
        tab.setAttribute("role", "tab");
        tab.setAttribute("aria-controls", panels[i].id);
        panels[i].setAttribute("role", "tabpanel");
        panels[i].setAttribute("aria-labelledby", tab.id);
        panels[i].setAttribute("tabindex", "0");
        var heading = panels[i].querySelector(".tabs__panel-heading");
        if (heading) heading.classList.add("sr-only");
      });

      function select(index, focus) {
        tabs.forEach(function (tab, i) {
          var on = i === index;
          tab.setAttribute("aria-selected", String(on));
          tab.setAttribute("tabindex", on ? "0" : "-1");
          panels[i].hidden = !on;
        });
        if (focus) tabs[index].focus();
      }

      list.addEventListener("click", function (event) {
        var tab = event.target.closest(".tabs__tab");
        if (!tab) return;
        event.preventDefault();
        select(tabs.indexOf(tab), false);
      });
      list.addEventListener("keydown", function (event) {
        var index = tabs.indexOf(doc.activeElement);
        if (index < 0) return;
        var rtl = getComputedStyle(container).direction === "rtl";
        var next = { ArrowRight: rtl ? -1 : 1, ArrowLeft: rtl ? 1 : -1 }[event.key];
        if (next) index = (index + next + tabs.length) % tabs.length;
        else if (event.key === "Home") index = 0;
        else if (event.key === "End") index = tabs.length - 1;
        else return;
        event.preventDefault();
        select(index, true);
      });

      var fromHash = panels.findIndex(function (panel) {
        return "#" + panel.id === window.location.hash;
      });
      container.classList.add("tabs--enhanced");
      select(fromHash >= 0 ? fromHash : 0, false);
    });
  }

  /* ---- File drop zones ---- */
  function initDropzones(scope) {
    each(scope, "[data-dropzone]", function (zone) {
      if (!enhanceOnce(zone, "dropzone")) return;
      var input = zone.querySelector('input[type="file"]');
      var shown = zone.querySelector("[data-dropzone-file]");
      if (!input) return;
      zone.classList.add("dropzone--enhanced");

      function showFile() {
        var names = Array.prototype.map.call(input.files || [], function (f) {
          return f.name;
        });
        if (shown) {
          shown.lastElementChild.textContent = names.join(", ");
          shown.hidden = names.length === 0;
        }
      }

      input.addEventListener("change", showFile);
      ["dragenter", "dragover"].forEach(function (type) {
        zone.addEventListener(type, function (event) {
          event.preventDefault();
          zone.classList.add("dropzone--over");
        });
      });
      ["dragleave", "dragend", "drop"].forEach(function (type) {
        zone.addEventListener(type, function () {
          zone.classList.remove("dropzone--over");
        });
      });
      zone.addEventListener("drop", function (event) {
        event.preventDefault();
        if (!event.dataTransfer || !event.dataTransfer.files.length) return;
        input.files = event.dataTransfer.files;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      });
    });
  }

  /* ---- Dialogs, dismissible alerts, error summaries ---- */
  function initDialogs(scope) {
    each(scope, "[data-dialog-open]", function (button) {
      if (!enhanceOnce(button, "dialog")) return;
      button.addEventListener("click", function () {
        var dialog = doc.getElementById(button.getAttribute("data-dialog-open"));
        if (dialog && dialog.showModal) dialog.showModal();
      });
    });
    each(scope, "[data-dismissible] [data-dismiss]", function (button) {
      if (!enhanceOnce(button, "dismiss")) return;
      button.addEventListener("click", function () {
        button.closest("[data-dismissible]").remove();
      });
    });
    var summary = scope.querySelector("[data-error-summary]");
    if (summary && enhanceOnce(summary, "summary")) summary.focus();
  }

  /* ---- Toasts ---- */
  var ICONS = { info: 0, success: 1, warning: 2, error: 3 };

  function toast(message, kind) {
    kind = ICONS.hasOwnProperty(kind) ? kind : "info";
    var region = doc.getElementById("toasts");
    var template = doc.getElementById("toast-template");
    var icons = doc.getElementById("toast-icons");
    if (!region || !template) return;
    var item = template.content.firstElementChild.cloneNode(true);
    item.classList.add("alert--" + kind);
    if (kind === "error") item.setAttribute("role", "alert");
    item.querySelector("[data-toast-message]").textContent = message;
    if (icons) {
      item
        .querySelector("[data-toast-icon]")
        .replaceWith(icons.content.children[ICONS[kind]].cloneNode(true));
    }
    var remove = function () {
      item.remove();
    };
    item.querySelector("[data-toast-close]").addEventListener("click", remove);
    region.appendChild(item);
    if (kind !== "error") setTimeout(remove, 6000);
    return item;
  }

  function initToastDemos(scope) {
    each(scope, "[data-toast-demo]", function (button) {
      if (!enhanceOnce(button, "toast")) return;
      button.addEventListener("click", function () {
        toast(button.getAttribute("data-message"), button.getAttribute("data-toast-demo"));
      });
    });
  }

  doc.addEventListener("toast", function (event) {
    var detail = event.detail || {};
    if (detail.message) toast(detail.message, detail.kind);
  });

  /* ---- Announcements and focus across htmx swaps (#83) ----
   * A polled fragment replaces itself, so a live region inside it would be new each time
   * and screen readers would not read it. Instead the fragment marks its news with
   * data-announce and the text goes to #announcer, which stays: when it changes, and at
   * most every 10 s unless marked data-announce="now" (a job that has finished). */
  var lastText = "";
  var lastTime = 0;

  function announce(scope) {
    var region = doc.getElementById("announcer");
    var items = scope.matches && scope.matches("[data-announce]") ? [scope] : [];
    items = items.concat(Array.prototype.slice.call(scope.querySelectorAll("[data-announce]")));
    if (!region || !items.length) return;
    var text = items
      .map(function (el) {
        return el.textContent.replace(/\s+/g, " ").trim();
      })
      .join(" ");
    var now = items.some(function (el) {
      return el.getAttribute("data-announce") === "now";
    });
    if (!text || text === lastText || (!now && Date.now() - lastTime < 10000)) return;
    lastText = text;
    lastTime = Date.now();
    region.textContent = text;
  }

  /* Keyboard focus inside a fragment that is swapped (a cancel button in a polled
   * progress fragment) goes to the same control in the new content. */
  var focusKey = null;

  function keyOf(el) {
    if (el.id) return "#" + el.id;
    var form = el.form || el.closest("form");
    var tag = el.tagName.toLowerCase();
    if (form && form.getAttribute("action")) {
      return 'form[action="' + form.getAttribute("action") + '"] ' + tag;
    }
    return el.getAttribute("href") ? tag + '[href="' + el.getAttribute("href") + '"]' : null;
  }

  doc.addEventListener("htmx:beforeSwap", function (event) {
    var active = doc.activeElement;
    var target = event.detail.target;
    focusKey = active && active !== doc.body && target && target.contains(active) ? keyOf(active) : null;
  });

  doc.addEventListener("htmx:afterSettle", function () {
    if (!focusKey) return;
    var el = null;
    try {
      el = doc.querySelector(focusKey);
    } catch (e) {
      /* a key that is not a valid selector: leave focus where it is */
    }
    focusKey = null;
    if (el && doc.activeElement !== el) el.focus();
  });

  function init(scope) {
    if (scope !== doc) announce(scope);
    initThemeToggle(scope);
    initTabs(scope);
    initDropzones(scope);
    initDialogs(scope);
    initToastDemos(scope);
  }

  window.Climpact = { toast: toast, chartPalette: chartPalette, setTheme: setTheme };

  if (doc.readyState === "loading") {
    doc.addEventListener("DOMContentLoaded", function () {
      init(doc);
    });
  } else {
    init(doc);
  }
  doc.addEventListener("htmx:load", function (event) {
    init(event.target);
  });
})();
