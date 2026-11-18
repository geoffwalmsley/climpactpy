/*
 * Copy a text (#239: the workspace Files' "Copy methods text").
 *
 * Without JavaScript a disclosure shows the text ([data-copy] > details); here a button
 * takes its place ([data-copy-button]), copies the text ([data-copy-text]) and says so
 * (#announcer). If the clipboard refuses, the text is shown as without JavaScript. The
 * index page's "Copy citation" works the same way (js/index-page.js).
 */
(function () {
  "use strict";

  var doc = document;
  doc.querySelectorAll("[data-copy]").forEach(function (box) {
    var details = box.querySelector("details");
    var button = box.querySelector("[data-copy-button]");
    var text = box.querySelector("[data-copy-text]").textContent.trim();
    if (!navigator.clipboard || !button || !details) return;
    details.hidden = true;
    button.hidden = false;
    button.addEventListener("click", function () {
      navigator.clipboard.writeText(text).then(
        function () {
          var said = button.getAttribute("data-copied");
          var region = doc.getElementById("announcer");
          if (region) region.textContent = said;
          var label = button.textContent;
          button.textContent = said;
          setTimeout(function () { button.textContent = label; }, 2000);
        },
        function () {
          button.hidden = true;
          details.hidden = false;
          details.open = true;
        }
      );
    });
  });
})();
