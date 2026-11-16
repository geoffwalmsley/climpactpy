/*
 * Forms with Cloudflare Turnstile's widget (#163), loaded by the {% turnstile %} tag with
 * the widget, so only when Turnstile is on. A form sent before its widget has a token is
 * refused, as when the sample's top button (outside the form, far above the widget) is
 * pressed at once. So the form is held: its buttons are marked busy, a status says why,
 * and it is sent with the same button as soon as its own widget has a token (Turnstile's
 * data-callback, and a poll in case Turnstile called back before this file ran). An error,
 * or no token within a minute, says so and offers to try again. Widgets added by htmx
 * swaps are rendered here: Turnstile renders only those in the page when it loads. The
 * texts come from the widget's data-text-wait, data-text-slow, data-text-failed and
 * data-text-retry (not data-retry, which is a Turnstile setting).
 */
(function () {
  "use strict";

  if (window.climpactTurnstileDone) return; // loaded again by an htmx swap

  var doc = document;
  var held = null; // the form waiting for its token: {form, submitter, status, timer, ...}

  function widgetOf(form) {
    return form.querySelector(".cf-turnstile");
  }

  function hasToken(form) {
    var widget = widgetOf(form);
    var input = widget.querySelector("[name=cf-turnstile-response]");
    try {
      if (window.turnstile.isExpired(widget)) return false;
    } catch (e) {
      /* not loaded yet: the field alone says */
    }
    return !!(input && input.value);
  }

  function setBusy(form, on) {
    Array.prototype.forEach.call(form.elements, function (el) {
      if (el.type !== "submit") return;
      ["aria-busy", "aria-disabled"].forEach(function (name) {
        if (on) el.setAttribute(name, "true");
        else el.removeAttribute(name);
      });
    });
  }

  function say(key, withRetry) {
    var widget = widgetOf(held.form);
    held.status.textContent = widget.getAttribute("data-text-" + key);
    if (!withRetry) return;
    var button = doc.createElement("button");
    button.type = "button";
    button.className = "button button--secondary button--sm";
    button.textContent = widget.getAttribute("data-text-retry");
    button.addEventListener("click", retry);
    held.status.append(" ", button);
  }

  function release() {
    clearInterval(held.timer);
    setBusy(held.form, false);
    held.status.remove();
    held = null;
  }

  function wait() {
    held.failed = held.slow = false;
    held.start = Date.now();
    setBusy(held.form, true);
    say("wait");
  }

  function retry() {
    try {
      window.turnstile.reset(widgetOf(held.form));
    } catch (e) {
      /* the poll still sends the form if a token comes */
    }
    wait();
    if (held.submitter) held.submitter.focus();
  }

  function fail() {
    held.failed = true;
    setBusy(held.form, false);
    say("failed", true);
  }

  function check() {
    if (!held) return;
    var form = held.form;
    if (!form.isConnected || !widgetOf(form)) return release();
    if (hasToken(form)) {
      var submitter = held.submitter;
      release();
      if (form.requestSubmit) form.requestSubmit(submitter);
      else if (submitter) submitter.click();
      else form.submit();
      return;
    }
    if (held.failed) return; // a token that comes later still sends the form
    var waited = Date.now() - held.start;
    if (waited > 60000) return fail();
    if (waited > 6000 && !held.slow) {
      held.slow = true;
      say("slow");
      var widget = widgetOf(form);
      var box = widget.getBoundingClientRect();
      if (box.top < 0 || box.bottom > window.innerHeight) widget.scrollIntoView({ block: "center" });
    }
  }

  /* Named by the widget's data-callback and data-error-callback. */
  window.climpactTurnstileDone = check;
  window.climpactTurnstileError = function () {
    if (held && !hasToken(held.form)) fail();
  };

  /* Capture, on the document: every way of sending a form (its buttons, a button outside
     it with form="...", Enter in a field) comes here before anything else. */
  doc.addEventListener(
    "submit",
    function (event) {
      var form = event.target;
      if (!form.querySelector || !widgetOf(form)) return;
      if (hasToken(form)) {
        if (held && held.form === form) release();
        return;
      }
      event.preventDefault();
      event.stopImmediatePropagation();
      if (held && held.form === form) {
        if (held.failed) retry();
        return;
      }
      if (held) release();
      var submitter = event.submitter && event.submitter.form === form ? event.submitter : null;
      var status = doc.createElement("p");
      status.className = "text-sm";
      status.setAttribute("role", "status");
      // Beside the button pressed (the top button's row, or the form's actions).
      var next = submitter && submitter.parentNode !== form ? submitter.parentNode : widgetOf(form);
      next.after(status);
      held = { form: form, submitter: submitter, status: status, start: Date.now() };
      held.timer = setInterval(check, 250);
      setBusy(form, true);
      // Filled once it is in the page, so that screen readers read it.
      setTimeout(function () {
        if (held && held.status === status && !held.slow && !held.failed) say("wait");
      }, 100);
    },
    true
  );

  /* Widgets that come with htmx content; those in the page at load are Turnstile's. */
  doc.addEventListener("htmx:load", function (event) {
    var scope = event.target;
    if (!window.turnstile || scope === doc.body) return;
    Array.prototype.forEach.call(scope.querySelectorAll(".cf-turnstile"), function (widget) {
      if (widget.firstChild || widget.hasAttribute("data-rendered")) return;
      widget.setAttribute("data-rendered", "");
      window.turnstile.render(widget);
    });
  });
})();
