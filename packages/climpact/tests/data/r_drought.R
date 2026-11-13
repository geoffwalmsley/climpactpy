# Prints Climpact's SPI/SPEI fit (services/calculate/custom_cspei.R, custom_cspi.R) and
# SPEI 1.8.1's hargreaves() on synthetic monthly series, for tests/test_drought.py; the
# output is stored in tests/data/r_drought.txt (C99 hex floats, NA for missing).
# Run in the R reference image (reference/r):
#   docker run --rm --platform linux/amd64 -v $CLIMPACT_DIR:/climpact:ro -v $PWD/tests/data:/probe:ro \
#     --entrypoint Rscript climpact-r-ref:3.4.3-amd64 /probe/r_drought.R > tests/data/r_drought.txt
# Monthly series 1961-2010 (600 months), base period 1971-2000. Cases:
#   - January has no precipitation in any base year: L2 = 0, so January is never fitted;
#   - April has only 4 base-period values: pwm.ub gives NaN, April is never fitted;
#   - July is dry in about a third of the years: at scale 1 SPI mixes in the zero probability;
#   - a few missing months, inside and outside the base period;
#   - one enormous month (2005-03) whose probability is 1: SPI/SPEI are Inf, then NA.
#   - hargreaves at the equator, Sydney, 62 N and the polar latitudes 75 N and 80 S
#     (sunset hour angle outside [-1, 1]), with months where Tr - 0.0123 P < 0.
suppressMessages({library(SPEI); library(lmomco)})
source("/climpact/services/calculate/custom_cspei.R")
source("/climpact/services/calculate/custom_cspi.R")
h <- function(x) ifelse(is.na(x), "NA", sprintf("%a", x))
set.seed(22)
n <- 600
month <- rep(1:12, 50)
year <- rep(1961:2010, each = 12)
base <- year >= 1971 & year <= 2000
prec <- round(rgamma(n, shape = 2, scale = 30), 1)
prec[month == 1 & base] <- 0
prec[month == 7 & runif(n) < 0.35] <- 0
prec[month == 4 & base & year > 1974] <- NA
prec[c(30, 200, 333, 590)] <- NA
prec[which(year == 2005 & month == 3)] <- 1e5
tmax <- round(25 + 6 * cos(2 * pi * (month - 1) / 12) + rnorm(n, 0, 1.5), 1)
tmin <- round(tmax - 8 - abs(rnorm(n, 0, 2)), 1)
tmax[c(45, 400)] <- NA
tmin[c(46, 400)] <- NA
cat("prec", h(prec), "\n")
cat("tmax", h(tmax), "\n")
cat("tmin", h(tmin), "\n")
for (lat in c(0, -33.86, 62, 75, -80)) {
  pet <- as.numeric(hargreaves(tmin, tmax, lat = lat, Pre = prec, na.rm = TRUE, verbose = FALSE))
  cat("pet", lat, h(pet), "\n")
}
pet <- as.numeric(hargreaves(tmin, tmax, lat = -33.86, Pre = prec, na.rm = TRUE, verbose = FALSE))
for (scale in c(1, 3, 24)) {
  spi <- cspi(ts(prec, freq = 12, start = c(1961, 1)), na.rm = TRUE, scale = scale,
              ref.start = c(1971, 1), ref.end = c(2000, 12))$fitted
  spei <- cspei(ts(prec - pet, freq = 12, start = c(1961, 1)), na.rm = TRUE, scale = scale,
                ref.start = c(1971, 1), ref.end = c(2000, 12))$fitted
  cat("spi", scale, h(as.numeric(spi)), "\n")
  cat("spei", scale, h(as.numeric(spei)), "\n")
}
