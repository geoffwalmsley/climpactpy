/*
 * The station workspace's header (#197, stations/_workspace.html).
 *
 * It stays in view as the page scrolls. The CSS's scroll-padding keeps an element that
 * takes focus, or a #fragment, out from under it (WCAG 2.4.11); this keeps that padding to
 * the header's real height, which changes with the window's width and the text size.
 * Without it the CSS's estimate applies. On a phone (#203) only the tabs and the Inputs
 * bar stay: the header sticks above the top of the window by the height of what is above
 * the tabs (--workspace-header-above), and the padding is what stays in view.
 *
 * The page's ⋯ menu (#203, a <details> disclosure on phones): Escape closes it and puts
 * focus back on its button; a click or focus outside it closes it.
 */
(function () {
  "use strict";

  var doc = document;
  var header = doc.querySelector("[data-workspace-header]");
  if (!header) return;
  var tabs = header.querySelector("nav");
  var style = doc.documentElement.style;
  function update() {
    style.setProperty("--workspace-header-height", header.offsetHeight + "px");
    if (!tabs) return;
    var above = tabs.getBoundingClientRect().top - header.getBoundingClientRect().top;
    style.setProperty("--workspace-header-above", Math.round(above) + "px");
  }
  update();
  if (window.ResizeObserver) new ResizeObserver(update).observe(header);
  else window.addEventListener("resize", update);

  var menu = header.querySelector("[data-page-menu]");
  if (!menu) return;
  var button = menu.querySelector("summary");
  menu.addEventListener("keydown", function (event) {
    if (event.key !== "Escape" || !menu.open) return;
    menu.open = false;
    button.focus();
    event.preventDefault();
  });
  function outside(event) {
    if (menu.open && !menu.contains(event.target)) menu.open = false;
  }
  doc.addEventListener("click", outside);
  doc.addEventListener("focusin", outside);
})();
