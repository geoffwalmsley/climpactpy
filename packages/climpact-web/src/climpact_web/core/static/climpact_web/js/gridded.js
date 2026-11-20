/* Gridded set-up page (#85, #293): All, None and "Without the slow ones" for the index
   checkboxes; a file's header (ncdump -h) in a dialog; Copy beside a CDO command. Without
   JavaScript the index buttons and Copy stay hidden, every index is ticked by default and
   Header opens the header's own page. */
(function () {
  "use strict";
  var doc = document;

  function setBoxes(name, test) {
    var boxes = doc.querySelectorAll('input[type="checkbox"][name="' + name + '"]');
    boxes.forEach(function (box) { box.checked = test(box); });
    if (boxes[0]) boxes[0].dispatchEvent(new Event("change", { bubbles: true }));
  }

  function announce(text) {
    var region = doc.getElementById("announcer");
    if (region) region.textContent = text;
  }

  function showButtons(scope) {
    scope.querySelectorAll("[data-check-tools], [data-copy-command]").forEach(function (el) {
      if (el.matches("[data-copy-command]") && !navigator.clipboard) return;
      el.hidden = false;
    });
  }

  showButtons(doc);
  // The CDO command comes and goes as the summary is swapped in out of band.
  doc.body.addEventListener("htmx:afterSettle", function () { showButtons(doc); });

  doc.addEventListener("click", function (event) {
    var t = event.target;
    var all = t.closest("[data-check-all]");
    var none = t.closest("[data-check-none]");
    var fast = t.closest("[data-check-fast]");
    if (all) setBoxes(all.getAttribute("data-check-all"), function () { return true; });
    if (none) setBoxes(none.getAttribute("data-check-none"), function () { return false; });
    if (fast) setBoxes(fast.getAttribute("data-check-fast"), function (box) { return !box.hasAttribute("data-slow"); });

    var copy = t.closest("[data-copy-command]");
    if (copy) {
      var text = copy.closest("[data-copy-box]").querySelector("[data-copy-source]").textContent;
      navigator.clipboard.writeText(text.trim()).then(function () {
        announce(copy.getAttribute("data-copied"));
      });
    }

    var link = t.closest("[data-file-header]");
    var dialog = doc.getElementById("file-header-dialog");
    if (link && dialog && dialog.showModal && !event.metaKey && !event.ctrlKey && !event.shiftKey) {
      event.preventDefault();
      fetch(link.href + "?format=text", { credentials: "same-origin" })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
        .then(function (text) {
          dialog.querySelector("[data-file-header-title]").textContent = link.getAttribute("data-file-header");
          dialog.querySelector("[data-file-header-text]").textContent = text;
          dialog.showModal();
        })
        .catch(function () { window.location.href = link.href; });
    }
  });
})();
