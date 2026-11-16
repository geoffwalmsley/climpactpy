/*
 * The New station page (#201). A chosen or dropped file is read at once: the form is sent
 * with its "Read the file" button (hidden here; without JavaScript the user presses it),
 * the details typed so far with it. Replace, on the file card, is a button that opens the
 * file picker and does the same (the file button of #174, inside the page's one form).
 * Back from reading, focus goes to the file card, unless an error summary took it.
 */
(function () {
  "use strict";

  function sendOnChoice(input, button) {
    if (!input || !button || !button.form) return;
    input.addEventListener("change", function () {
      if (input.files && input.files.length) button.form.requestSubmit(button);
    });
  }

  var read = document.getElementById("read-file");
  if (read) {
    read.hidden = true;
    sendOnChoice(read.form.querySelector("[data-dropzone] input[type=file]"), read);
  }

  var replace = document.querySelector("[data-setup-replace]");
  if (replace) {
    var label = replace.querySelector("label[data-class]");
    label.className += " " + label.getAttribute("data-class");
    replace.classList.add("file-button--enhanced");
    sendOnChoice(replace.querySelector("input[type=file]"), replace.querySelector("button"));
  }

  var card = document.querySelector("[data-focus-on-load]");
  if (card && !document.querySelector("[data-error-summary]")) card.focus();
})();
