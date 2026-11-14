/* Gridded set-up page (#85): "Choose all" and "Choose none" for the index checkboxes.
   Without JavaScript the buttons stay hidden and every box is ticked by default. */
(function () {
  "use strict";
  function setAll(name, checked) {
    document.querySelectorAll('input[type="checkbox"][name="' + name + '"]').forEach(function (box) {
      box.checked = checked;
    });
    var first = document.querySelector('input[type="checkbox"][name="' + name + '"]');
    if (first) first.dispatchEvent(new Event("change", { bubbles: true }));
  }
  document.querySelectorAll("[data-check-tools]").forEach(function (tools) {
    tools.hidden = false;
  });
  document.addEventListener("click", function (event) {
    var all = event.target.closest("[data-check-all]");
    var none = event.target.closest("[data-check-none]");
    if (all) setAll(all.getAttribute("data-check-all"), true);
    if (none) setAll(none.getAttribute("data-check-none"), false);
  });
})();
