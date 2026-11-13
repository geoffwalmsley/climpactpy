# Prints zyp 0.11-1's Sen's slope (zyp.sen) and confint.zyp bounds, Kendall 2.2.2's varS,
# and the seasonal series plot.call (services/plot_indices.R) builds from monthly values,
# on synthetic series, for tests/test_trends.py; the output is stored in
# tests/data/r_trends.txt (C99 hex floats, NA for missing).
# Run in the R reference image (reference/r):
#   docker run --rm --platform linux/amd64 -v $PWD/tests/data:/probe:ro \
#     --entrypoint Rscript climpact-r-ref:3.4.3-amd64 /probe/r_trends.R \
#     | grep -v '^WARNING' > tests/data/r_trends.txt
# (Kendall prints "WARNING: Error exit, tauk2. IFAULT = 12" with cat for the constant series.)
# Cases (y values; x = 0, 1, ... with the missing values left out, as plot.call does):
#   short:    12 values, two missing (a slope count small enough to check by hand);
#   counts:   80 annual day counts with many ties;
#   monthly:  960 monthly counts 0-5, so Kendall's single-precision Var(S) is rounded;
#   constant: every value equal: Kendall leaves Var(S) at 0, both bounds are the median;
#   f32ties:  values that differ as doubles but are equal in single precision;
#   decimals: 60 values with one decimal, as temperatures, with missing values;
#   three:    3 values: the lower index round((3 - c) / 2) is 0, which selects nothing,
#             so R recycles the upper bound into both bounds.
suppressMessages({library(zyp); library(Kendall); library(zoo)})
h <- function(x) ifelse(is.na(x), "NA", sprintf("%a", x))
emit <- function(name, y1) {
  x1 <- seq(0, length(y1) - 1, 1)
  x2 <- x1[!is.na(y1)]
  y2 <- y1[!is.na(y1)]
  zsen <- zyp.sen(y2 ~ x2)
  ci <- confint.zyp(zsen, level = 0.95)
  k <- Kendall(x2, y2)
  cat("y", name, h(y1), "\n")
  cat("trend", name, h(c(ci[2, 1], zsen[[1]][2], ci[2, 2], k$varS)), "\n")
}
set.seed(18)
emit("short", c(3.2, 4.1, NA, 2.8, 5.0, 5.5, 4.9, NA, 6.1, 5.8, 7.0, 6.6))
emit("counts", as.numeric(rpois(80, 4)))
emit("monthly", as.numeric(pmin(rpois(960, 1.2), 5)))
emit("constant", rep(0, 40))
emit("f32ties", c(1, 1 + 1e-12, 2, 2 - 1e-12, 3, 1, 2, 3, 3 + 1e-13, 2, 1, 4))
y <- round(rnorm(60, 20, 2), 1)
y[c(5, 17, 18, 40)] <- NA
emit("decimals", y)
emit("three", c(1, 2, 4))

# Seasonal series, copied from plot.call: 1961-1970 monthly values with gaps.
months <- rep(1:12, 10)
years <- rep(1961:1970, each = 12)
v <- round(runif(120, 0, 30), 1)
v[c(3, 14, 15, 50, 119)] <- NA
cat("monthly_values", h(v), "\n")
min_months <- 3
fs <- list(
  max = function(x) ifelse(sum(!is.na(x)) < min_months, NA, max(x, na.rm = FALSE)),
  sum = function(x) ifelse(sum(!is.na(x)) < min_months, NA, sum(x, na.rm = FALSE)),
  mean = function(x) ifelse(sum(!is.na(x)) < min_months, NA, mean(x, na.rm = FALSE))
)
for (fname in names(fs)) {
  f <- fs[[fname]]
  df <- data.frame(months, years, v)
  names(df) <- c("months", "years", "values")
  ym <- as.yearmon(paste(months, years), "%m %Y")
  yq <- as.yearqtr(head(ym + 1 / 12, -1))
  Ag <- aggregate(head(df$values, -1) ~ yq, head(df, -1), f, na.action = NULL)
  names(Ag) <- c("yq", "values")
  for (q in 1:4) {
    s <- Ag[grepl(paste0("Q", q), Ag$yq), ]
    cat("season", fname, c("DJF", "MAM", "JJA", "SON")[q], h(s$values), "\n")
  }
}
