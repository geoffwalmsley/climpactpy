/* Gridded set-up page (#85, #293): All, None and "Without the slow ones" for the index
   checkboxes; a file's header (ncdump -h) in a dialog; Copy beside a CDO command; Browse's
   folder listing (#320), which htmx puts under its field: choosing a file or folder fills
   the field (and the summary panel checks it again), Close shuts it, Enter in its folder
   field opens that folder, and one listing is open at a time. Without JavaScript the index
   buttons and Copy stay hidden, every index is ticked by default, Header opens the
   header's own page and Browse posts the form. */
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

  function closeListing(field, focus) {
    var slot = doc.querySelector('[data-browse-slot="' + field + '"]');
    if (slot) slot.replaceChildren();
    if (focus) focus.focus();
  }

  // A listing just put in its place: close the other one, and take focus to its folder
  // field (the button that moved it has gone).
  doc.body.addEventListener("htmx:afterSwap", function (event) {
    var slot = event.detail.target;
    if (!slot.matches || !slot.matches("[data-browse-slot]")) return;
    doc.querySelectorAll("[data-browse-slot]").forEach(function (other) {
      if (other !== slot) other.replaceChildren();
    });
    var folder = slot.querySelector("[data-browse-folder]");
    if (folder) folder.focus();
  });

  doc.addEventListener("keydown", function (event) {
    var folder = event.target.closest && event.target.closest("[data-browse-folder]");
    if (!folder || event.key !== "Enter") return;
    event.preventDefault();
    var open = folder.closest("[data-browse-listing]").querySelector("[data-browse-open]");
    if (open) open.click();
  });

  doc.addEventListener("click", function (event) {
    var t = event.target;
    var pick = t.closest("[data-browse-pick]");
    var shut = t.closest("[data-browse-close]");
    if (pick || shut) {
      event.preventDefault();
      var field = (pick || shut).closest("[data-browse-listing]").getAttribute("data-browse-listing");
      var input = doc.getElementsByName(field)[0];
      if (pick && input) {
        input.value = pick.getAttribute("data-browse-pick");
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }
      closeListing(field, pick ? input : doc.querySelector('[data-browse="' + field + '"]'));
      return;
    }
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
