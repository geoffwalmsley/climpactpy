/* The theme the user picked (ui.js), applied before the page paints: base.html loads this
   file without defer, in <head> after the stylesheet (#137: no inline script). */
try {
  var t = localStorage.getItem("climpact-theme");
  if (t === "dark" || t === "light") document.documentElement.dataset.theme = t;
} catch (e) {}
