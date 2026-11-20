// On this page (#325, help/_toc.html): marks the section being read, the last heading
// above the top third of the window, with aria-current="true" in both of its lists.
// Without JavaScript nothing is marked; the links work as they are.
(function () {
  "use strict";
  var links = document.querySelectorAll("[data-help-toc] a[href^='#']");
  var ids = [], seen = {};
  links.forEach(function (a) {
    var id = decodeURIComponent(a.hash.slice(1));
    if (!seen[id] && document.getElementById(id)) { seen[id] = 1; ids.push(id); }
  });
  if (!ids.length) return;
  var queued = false;
  function mark() {
    queued = false;
    var line = innerHeight / 3, current = ids[0];
    ids.forEach(function (id) {
      if (document.getElementById(id).getBoundingClientRect().top <= line) current = id;
    });
    links.forEach(function (a) {
      if (decodeURIComponent(a.hash.slice(1)) === current) a.setAttribute("aria-current", "true");
      else a.removeAttribute("aria-current");
    });
  }
  function queue() { if (!queued) { queued = true; requestAnimationFrame(mark); } }
  addEventListener("scroll", queue, { passive: true });
  addEventListener("resize", queue);
  mark();
})();
