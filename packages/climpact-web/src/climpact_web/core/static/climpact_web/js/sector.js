/* Step 5 of a station, sector data (#90): when a sector file is chosen, fill the y-axis
   label with the file name up to its first "_" or "." (as Climpact for R does), unless the
   user has typed one. Without JavaScript the server uses the same default for an empty
   label. */
(function () {
  "use strict";
  var file = document.querySelector("[data-sector-file]");
  var label = document.querySelector("[data-sector-label]");
  if (!file || !label) return;
  var filled = "";
  label.addEventListener("input", function () { filled = ""; });
  file.addEventListener("change", function () {
    var chosen = file.files && file.files[0];
    if (!chosen || (label.value && label.value !== filled)) return;
    filled = chosen.name.split(/[_.]/)[0];
    label.value = filled;
  });
})();
