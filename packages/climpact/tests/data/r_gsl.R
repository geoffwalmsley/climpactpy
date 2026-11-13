# Prints climdex.pcic's climdex.gsl (gsl.mode "GSL", include.exact.dates = TRUE, as Climpact
# calls it) for tests/data/gsl_synthetic.txt, one growing-season scenario per year 2001-2008,
# for tests/test_gsl.py. Run in the R reference image (reference/r):
#   docker run --rm --platform linux/amd64 -v $PWD/packages/climpact/tests/data:/probe:ro \
#     --entrypoint Rscript climpact-r-ref:3.4.3-amd64 /probe/r_gsl.R
# Latitude 45 is northern; latitudes 0 and -30 are southern (climdex: lat > 0 is northern).
suppressMessages(library(climdex.pcic))
d <- read.table("/probe/gsl_synthetic.txt", col.names = c("y", "m", "d", "prcp", "tmax", "tmin"),
                na.strings = "-99.9")
dates <- as.PCICt(sprintf("%04d-%02d-%02d", d$y, d$m, d$d), cal = "gregorian")
for (lat in c(45, 0, -30)) {
  ci <- suppressWarnings(climdexInput.raw(tmax = d$tmax, tmin = d$tmin, prec = d$prcp,
    tmax.dates = dates, tmin.dates = dates, prec.dates = dates, base.range = c(2001, 2003),
    northern.hemisphere = lat > 0))
  g <- climdex.gsl(ci, include.exact.dates = TRUE)
  for (i in seq_len(nrow(g))) cat(lat, rownames(g)[i], g$start[i], g$sl[i], g$end[i], "\n")
}
