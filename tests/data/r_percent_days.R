# Prints Climpact's txgt50p for two small synthetic stations, for tests/test_temperature_percentiles.py.
# Run in the R reference image (reference/r):
#   docker run --rm --platform linux/amd64 -v $CLIMPACT_DIR:/climpact:ro -v $PWD/tests/data:/probe:ro \
#     --entrypoint Rscript climpact-r-ref:3.4.3-amd64 /probe/r_percent_days.R
# Output (climdex.pcic 1.2-0 with Climpact's percent.days.op.threshold):
#   2001 2002 2003 2004
#      0   50  100  100
#   2002 2003 2004
#      0  200  100
suppressMessages(library(climdex.pcic))
src <- readLines("/climpact/server/climpact.etsci-functions.r")
a <- grep("^get.years <- function", src); b <- grep("^climdex.tn10p <- function", src) - 1
# Climpact's override of percent.days.op.threshold, evaluated inside the climdex.pcic namespace
percent.days.op.threshold <- eval(parse(text = src[a:b])[[2]])
environment(percent.days.op.threshold) <- asNamespace("climdex.pcic")
txgt50p <- function(ci, freq) percent.days.op.threshold(ci@data$tmax, ci@dates, ci@jdays, ci@date.factors[[freq]], ci@quantiles$tmax$outbase$q50, ci@quantiles$tmax$inbase$q50, ci@base.range, ">", ci@max.missing.days[freq]) * ci@namasks[[freq]]$tmax
run <- function(start, vals) {
  d <- seq(as.Date(paste0(start, "-01-01")), as.Date("2004-12-31"), by = "day")
  y <- as.integer(format(d, "%Y"))
  tx <- vals[as.character(y)]
  dates <- as.PCICt(format(d), cal = "gregorian")
  ci <- climdexInput.raw(tmax = tx, tmin = tx - 5, prec = rep(0, length(d)), tmax.dates = dates, tmin.dates = dates, prec.dates = dates,
                         base.range = c(2001, 2003), temp.qtiles = c(0.05, 0.1, 0.5, 0.9, 0.95))
  print(txgt50p(ci, "annual"))
}
run(2001, c("2001" = 1, "2002" = 2, "2003" = 3, "2004" = 2.5))
run(2002, c("2002" = 2, "2003" = 3, "2004" = 2.5))
