/*
 * The station workspace's sticky header (#197, stations/_workspace.html). The CSS's
 * scroll-padding keeps an element that takes focus, or a #fragment, out from under the
 * header (WCAG 2.4.11); this keeps that padding to the header's real height, which changes
 * with the window's width and the text size. Without it the CSS's estimate applies.
 */
(function () {
  "use strict";

  var header = document.querySelector("[data-workspace-header]");
  if (!header) return;
  function update() {
    document.documentElement.style.setProperty("--workspace-header-height", header.offsetHeight + "px");
  }
  update();
  if (window.ResizeObserver) new ResizeObserver(update).observe(header);
  else window.addEventListener("resize", update);
})();
