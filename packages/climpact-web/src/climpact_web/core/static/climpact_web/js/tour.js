/*
 * climpact-web first-run tour (#81). Progressive enhancement: without this file (or
 * without JavaScript) the page is unchanged. No dependencies.
 *
 * The page provides:
 *   <script type="application/json" id="tour-steps">[{"target", "title", "text"}, ...]</script>
 *   <div class="tour-invite" hidden data-tour-invite> ... [data-tour-start] [data-tour-dismiss]
 *   <template id="tour-labels" data-next data-back data-done data-skip data-count></template>
 * A first visit shows the invitation; starting, finishing or dismissing the tour stores
 * "done" in localStorage ("climpact-tour"), so it is offered once. ?tour=1 in the address
 * (the help page's "Take the tour" link) starts it at once. Steps whose target is not on
 * the page are skipped. The tour box is a non-modal dialog: focus moves to it, Escape
 * closes it and focus returns to where it was.
 */
(function () {
  "use strict";

  var KEY = "climpact-tour";
  var doc = document;

  function stored() {
    try {
      return window.localStorage.getItem(KEY);
    } catch (e) {
      return null;
    }
  }

  function remember() {
    try {
      window.localStorage.setItem(KEY, "done");
    } catch (e) {
      /* private mode: the tour is offered again next time */
    }
  }

  function init() {
    var data = doc.getElementById("tour-steps");
    var labels = doc.getElementById("tour-labels");
    if (!data || !labels) return;
    var steps;
    try {
      steps = JSON.parse(data.textContent).filter(function (step) {
        return doc.querySelector(step.target);
      });
    } catch (e) {
      return;
    }
    if (!steps.length) return;

    var invite = doc.querySelector("[data-tour-invite]");
    var box = null;
    var index = 0;
    var returnFocus = null;
    var target = null;

    function label(name) {
      return labels.getAttribute("data-" + name) || "";
    }

    function hideInvite() {
      if (invite) invite.hidden = true;
    }

    function close() {
      remember();
      if (target) target.classList.remove("tour-target");
      if (box) box.remove();
      box = null;
      doc.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", place);
      // Back to where the tour was started from; when that is gone or hidden (the
      // invitation's button), to the main content rather than to nowhere (#83).
      if (returnFocus && doc.contains(returnFocus) && returnFocus.offsetParent) returnFocus.focus();
      else if (doc.getElementById("main")) doc.getElementById("main").focus();
    }

    function onKey(event) {
      if (event.key === "Escape") close();
    }

    function button(text, kind, handler) {
      var b = doc.createElement("button");
      b.type = "button";
      b.className = "button button--sm" + (kind ? " button--" + kind : "");
      b.textContent = text;
      b.addEventListener("click", handler);
      return b;
    }

    function place() {
      if (!box || !target) return;
      var narrow = window.matchMedia && window.matchMedia("(max-width: 40rem)").matches;
      box.classList.toggle("tour--docked", narrow);
      if (narrow) {
        box.style.left = box.style.top = "";
        return;
      }
      var rect = target.getBoundingClientRect();
      var width = box.offsetWidth;
      var gap = 16;
      var left = rect.left + window.scrollX;
      if (doc.documentElement.dir === "rtl") left = rect.right + window.scrollX - width;
      left = Math.max(gap, Math.min(left, window.scrollX + doc.documentElement.clientWidth - width - gap));
      var top = rect.bottom + window.scrollY + gap;
      if (rect.bottom + box.offsetHeight + gap > window.innerHeight && rect.top > box.offsetHeight + gap) {
        top = rect.top + window.scrollY - box.offsetHeight - gap;
      }
      box.style.left = left + "px";
      box.style.top = top + "px";
    }

    function show(i) {
      index = i;
      var step = steps[i];
      if (target) target.classList.remove("tour-target");
      target = doc.querySelector(step.target);
      if (!target) return close();
      target.classList.add("tour-target");
      var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      target.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });

      if (!box) {
        box = doc.createElement("div");
        box.className = "tour";
        box.setAttribute("role", "dialog");
        box.setAttribute("aria-modal", "false");
        box.setAttribute("aria-labelledby", "tour-title");
        box.setAttribute("aria-describedby", "tour-text");
        doc.body.appendChild(box);
        doc.addEventListener("keydown", onKey);
        window.addEventListener("resize", place);
      }
      box.innerHTML = "";
      var title = doc.createElement("h2");
      title.className = "tour__title";
      title.id = "tour-title";
      title.tabIndex = -1;
      title.textContent = step.title;
      var text = doc.createElement("p");
      text.className = "tour__text";
      text.id = "tour-text";
      text.textContent = step.text;
      var footer = doc.createElement("div");
      footer.className = "tour__footer";
      var count = doc.createElement("span");
      count.className = "tour__count text-sm text-text-muted";
      count.textContent = label("count").replace("{step}", i + 1).replace("{total}", steps.length);
      footer.appendChild(count);
      if (i < steps.length - 1) footer.appendChild(button(label("skip"), "ghost", close));
      if (i > 0) footer.appendChild(button(label("back"), "secondary", function () { show(index - 1); }));
      var last = i === steps.length - 1;
      footer.appendChild(button(last ? label("done") : label("next"), "", function () {
        if (last) close();
        else show(index + 1);
      }));
      box.appendChild(title);
      box.appendChild(text);
      box.appendChild(footer);
      place();
      window.setTimeout(place, reduce ? 0 : 350); // after the smooth scroll
      title.focus({ preventScroll: true });
    }

    function start(event) {
      returnFocus = (event && event.currentTarget) || doc.activeElement;
      hideInvite();
      remember();
      show(0);
    }

    Array.prototype.forEach.call(doc.querySelectorAll("[data-tour-start]"), function (b) {
      b.addEventListener("click", start);
    });
    Array.prototype.forEach.call(doc.querySelectorAll("[data-tour-dismiss]"), function (b) {
      b.addEventListener("click", function () {
        hideInvite();
        remember();
      });
    });

    if (/[?&]tour=1\b/.test(window.location.search)) {
      start();
    } else if (invite && stored() !== "done") {
      invite.hidden = false;
    }
  }

  if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", init);
  else init();
})();
