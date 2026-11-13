# Runs R's fourboxes (services/check/fourboxes.R, the qc/outliers file) on the synthetic
# stations written by tests/data/make_fourboxes_synthetic.py, for tests/test_qc.py.
# Writes tests/data/r_fourboxes_<station>_<iqr temp>_<iqr prec>_outliers.csv.
# Run in the R reference image (reference/r), with the Climpact repo mounted:
#   docker run --rm --platform linux/amd64 -v $PWD/packages/climpact/tests/data:/probe \
#     -v $CLIMPACT_DIR:/climpact:ro --entrypoint Rscript climpact-r-ref:3.4.3-amd64 \
#     /probe/r_fourboxes.R
version.climpact <- "3.4.3"
for (e in parse("/climpact/server/climpact.GUI-functions.r")) {
  if (is.call(e) && identical(e[[1]], as.name("<-")) && identical(e[[2]], as.name("write_header"))) eval(e)
}
source("/climpact/services/check/fourboxes.R")
run <- function(station, temp, prec) {
  metadata <- list(stationName = station, lat = 0, lon = 0, base.start = 1971, base.end = 2000)
  out <- file.path("/probe", paste("r_fourboxes", station, temp, prec, sep = "_"))
  fourboxes(file.path("/probe", paste0("fourboxes_", station, ".txt")), out, save = 1,
            temp, prec, metadata, mediaType = "pdf")
  invisible(file.remove(paste0(out, "_boxes.pdf")))
}
run("edges", 3, 5)
run("edges", 1.5, 2)
run("dry", 3, 5)
