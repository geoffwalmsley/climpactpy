/*
 * The site header stays in view on every page (#284). This keeps --site-header-measured
 * to its real height, which changes with the width and the text size; header.css turns
 * it into --site-header-height, which the context bar, the sticky panes and the scroll
 * padding stay under. Without it the CSS's estimate applies.
 */
(function () {
  "use strict";

  var header = document.querySelector(".site-header");
  if (!header) return;
  var style = document.documentElement.style;
  function update() {
    style.setProperty("--site-header-measured", header.offsetHeight + "px");
  }
  update();
  if (window.ResizeObserver) new ResizeObserver(update).observe(header);
  else window.addEventListener("resize", update);
})();
