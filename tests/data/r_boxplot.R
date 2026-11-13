# Prints R's fivenum(x) and boxplot.stats(x, coef)$stats, which the outlier check
# (services/check/fourboxes.R, through boxplot) uses, for tests/test_qc.py. The output
# is stored in tests/data/r_boxplot.txt, one case a line: "coef;x;fivenum;stats", each
# a space-separated list of C99 hex floats (NA for missing).
# Run in the R reference image (reference/r):
#   docker run --rm --platform linux/amd64 -v $PWD/tests/data:/probe:ro \
#     --entrypoint Rscript climpact-r-ref:3.4.3-amd64 /probe/r_boxplot.R > tests/data/r_boxplot.txt
# Cases: n = 1 to 12 (odd and even), longer samples with outliers at several
# coefficients, ties, an interquartile range of 0, missing values, values exactly on a
# fence, coef = 0, and no values at all.
set.seed(26)
hex <- function(v) paste(ifelse(is.na(v), "NA", sprintf("%a", v)), collapse = " ")
case <- function(x, coef) {
  cat(coef, ";", hex(x), ";", hex(fivenum(x)), ";", hex(boxplot.stats(x, coef)$stats), "\n",
      sep = "")
}
for (n in 1:12) case(round(rnorm(n, 15, 5), 1), 3)
for (n in c(30, 31, 89, 90, 93)) {
  x <- c(round(rnorm(n - 3, 15, 5), 1), 60.2, -40.1, 33.3)
  for (coef in c(1.5, 3, 5)) case(x, coef)
}
case(round(rexp(91, 1 / 4), 1) + 0.1, 5)
case(c(rep(10, 20), 10.1, 9.9), 3)
case(c(rep(c(19, 19.5, 20, 20.3, 20.5, 21.1), 10), 25.9, 26, 14.7, 14.6), 3)
case(c(0, 1, 2, 3, 4, 13, 13.1), 3)
case(c(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 1.2, 1.3, -0.5, -0.6), 1)
case(c(NA, 5.5, 3.2, NA, 8.1, 100.4, 2.2), 3)
case(c(1, 2, 3, 50), 0)
case(numeric(0), 3)
case(c(NA, NA), 3)
