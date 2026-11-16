/*
 * The Inputs panel's side sheets (#198, stations/_input_sheets.html). An input's Edit is a
 * link to its form's own page; here it opens the sheet with the same form instead, a
 * modal <dialog>: the page behind is inert, focus stays in the sheet and Escape closes it
 * (the browser's own). Focus goes to the form's first field. Cancel, the close button or
 * a click on the backdrop closes it too, and closing discards what was typed; focus then
 * returns to the Edit link.
 */
(function () {
  "use strict";

  var doc = document;

  function firstField(sheet) {
    return sheet.querySelector(".sheet__body :is(input, select, textarea):not([type=hidden])");
  }

  function open(link) {
    var sheet = doc.getElementById(link.getAttribute("data-sheet-open"));
    if (!sheet || !sheet.showModal) return false;
    sheet.showModal();
    var field = firstField(sheet);
    if (field) field.focus();
    return true;
  }

  function reset(sheet) {
    var form = sheet.querySelector("form");
    if (form) form.reset();
  }

  doc.addEventListener("click", function (event) {
    var target = event.target;
    if (!target.closest) return;
    var link = target.closest("[data-sheet-open]");
    if (link) {
      if (open(link)) event.preventDefault();
      return;
    }
    var close = target.closest("[data-sheet-close]");
    if (close) {
      close.closest("dialog").close();
      return;
    }
    /* The dialog fills the screen's height; its panel holds everything, so a click on
       the dialog itself is a click on the backdrop. */
    if (target.matches("dialog[data-sheet]")) target.close();
  });

  Array.prototype.forEach.call(doc.querySelectorAll("dialog[data-sheet]"), function (sheet) {
    sheet.addEventListener("close", function () {
      reset(sheet);
    });
  });
})();
