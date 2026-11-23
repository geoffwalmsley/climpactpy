# Reference results for the homogeneity break detection (#34).
#
#   Rscript run_homogeneity.R --series <run>.csv --out <dir> [--level 0.95] [--min-years 5]
#                             [--seed 1] [--sims 20000]
#
# --series is a CSV written by reference/homogeneity/make_series.py: one row per period of
# each tested series, columns variable (TX, TN, PRCP), series (annual, monthly), year, month
# (0 for annual series) and value (empty when missing; PRCP is the log of the annual total).
#
# Writes to --out:
#   tests.csv    every Pettitt and SNHT test of the binary segmentation (trend::pettitt.test,
#                trend::snh.test): the segment tested (start, end: 1-based positions among
#                the series' non-missing values), the change point k (last value before the
#                break), the statistic, the p-value and whether the break was accepted.
#                Monthly series are tested as anomalies from each calendar month's mean.
#   rhtests.csv  the changepoints RHtestsV4 reports: FindU (PMFred) and FindU.wRef (PMTred,
#                with a reference series of zeros, so the base series' anomalies are tested),
#                parsed from its _1Cs.txt and _Ustat.txt files.
#   rhtests_series.csv  one row per series and method: the number of changepoints, or
#                RHtests' error message.
#   rnorm.csv    set.seed(--seed); rnorm(10), for the Python port of R's random numbers.
suppressMessages(library(trend))

args <- commandArgs(trailingOnly = TRUE)
opt <- function(name, default = NULL) {
  i <- match(paste0("--", name), args)
  if (is.na(i)) default else args[i + 1]
}
series_file <- opt("series")
out <- opt("out")
level <- as.numeric(opt("level", "0.95"))
min_years <- as.integer(opt("min-years", "5"))
seed <- as.integer(opt("seed", "1"))
sims <- as.integer(opt("sims", "20000"))
alpha <- 1 - level
stopifnot(!is.null(series_file), !is.null(out))
dir.create(out, showWarnings = FALSE, recursive = TRUE)

data <- read.csv(series_file, stringsAsFactors = FALSE)
keys <- unique(data[, c("variable", "series")])

num <- function(x) sprintf("%.17g", x)

# ---- Pettitt and SNHT, with binary segmentation ----------------------------------------

run_test <- function(method, x) {
  if (method == "pettitt") {
    r <- pettitt.test(x)
  } else {
    set.seed(seed)
    r <- snh.test(x, m = sims)
  }
  list(k = unname(r$estimate[1]), statistic = unname(r$statistic), p = r$p.value)
}

segment <- function(method, x, offset, min_n) {
  n <- length(x)
  if (n < 2 * min_n) return(NULL)
  r <- run_test(method, x)
  accepted <- r$p <= alpha && r$k >= min_n && n - r$k >= min_n
  row <- data.frame(start = offset + 1, end = offset + n, k = offset + r$k,
                    statistic = num(r$statistic), p_value = num(r$p), accepted = accepted)
  if (!accepted) return(row)
  rbind(row,
        segment(method, x[1:r$k], offset, min_n),
        segment(method, x[(r$k + 1):n], offset + r$k, min_n))
}

anomalies <- function(s) {
  if (s$series[1] != "monthly") return(s$value)
  s$value - ave(s$value, s$month, FUN = function(v) mean(v, na.rm = TRUE))
}

tests <- NULL
for (i in seq_len(nrow(keys))) {
  s <- data[data$variable == keys$variable[i] & data$series == keys$series[i], ]
  x <- anomalies(s)
  ok <- !is.na(x)
  per_year <- if (s$series[1] == "monthly") 12 else 1
  for (method in c("pettitt", "snht")) {
    rows <- segment(method, x[ok], 0, min_years * per_year)
    if (is.null(rows)) next
    rows$last_year <- s$year[ok][rows$k]
    rows$last_month <- s$month[ok][rows$k]
    tests <- rbind(tests, cbind(variable = keys$variable[i], series = keys$series[i],
                                method = method, rows))
  }
}
write.csv(tests, file.path(out, "tests.csv"), row.names = FALSE, quote = FALSE)

# ---- RHtestsV4: FindU (PMFred) and FindU.wRef (PMTred) -----------------------------------

source("/opt/rhtests/RHtestsV4_20190301.r")
MISSING <- "-99.9"
work <- tempfile("rhtests")
dir.create(work)

# RHtests input: year, month, day, value; month and day 0 for annual series, day 0 for
# monthly ones (the user manual's layout).
write_rhtests <- function(file, s, values) {
  v <- ifelse(is.na(values), MISSING, num(values))
  writeLines(paste(s$year, s$month, 0, v), file)
}

parse_1cs <- function(file) {
  lines <- readLines(file)[-1]
  lines <- lines[nzchar(trimws(lines))]
  pat <- paste0("^\\s*1\\s+(Yes|\\?|No|YifD)\\s*(-?[0-9]+)\\s*\\(\\s*([-0-9.]+)-\\s*([-0-9.]+)\\)",
                "\\s*([-0-9.]+)\\s+([-0-9.]+|NaN|Inf)\\s*\\(\\s*([-0-9.]+)-\\s*([-0-9.]+)\\)")
  m <- regmatches(lines, regexec(pat, lines))
  do.call(rbind, lapply(m, function(g) {
    if (length(g) == 0) stop("cannot parse _1Cs.txt line")
    data.frame(label = g[2], date = g[3], prob_low = g[4], prob_high = g[5],
               statistic = g[7], cv_low = g[8], cv_high = g[9], stringsAsFactors = FALSE)
  }))
}

parse_ustat <- function(file, method) {
  lines <- readLines(file)
  pat <- paste0("^", method, " : c=\\s*([0-9]+); \\(Time\\s*(-?[0-9]+)\\); Type= 1; p=\\s*([-0-9.]+|NaN)\\(",
                ".*\\); P[TF]max=\\s*([-0-9.]+); CV95=\\s*([-0-9.]+)\\(.*\\); Nseg=\\s*([0-9]+)")
  m <- regmatches(lines, regexec(pat, lines))
  m <- m[lengths(m) > 0]
  stats <- do.call(rbind, lapply(m, function(g)
    data.frame(index = g[2], date = g[3], prob = g[4], cv = g[6], nseg = g[7],
               stringsAsFactors = FALSE)))
  if (method == "PMF") {
    steps <- regmatches(lines, regexec("^[0-9]+ (-?[0-9]+) stepsize= ([-0-9.]+|NA)", lines))
    steps <- do.call(rbind, lapply(steps[lengths(steps) > 0], function(g)
      data.frame(date = g[2], step = g[3], stringsAsFactors = FALSE)))
    stats <- merge(stats, steps, by = "date", sort = FALSE)
  } else {
    at <- grep("^Step-sizes estimated from difference series:", lines)
    values <- character(0)
    j <- at + 1
    while (j <= length(lines) && grepl("^[-0-9. ]+$", lines[j])) {
      values <- c(values, strsplit(trimws(lines[j]), "\\s+")[[1]])
      j <- j + 1
    }
    stats$step <- values
  }
  stats
}

clear_globals <- function() {
  # RHtests passes its data through global variables; FindU.wRef does not stop when
  # Read.wRef fails, so stale ones from the previous series must not be left behind.
  rm(list = intersect(c("Y0", "Ti", "TiB", "IY0", "IY0flg", "IYBflg", "Imd", "Icy", "Nt",
                        "itable", "ori.itable", "ooflg", "bdata", "ori.bdata", "owflg",
                        "ErrorMSG"), ls(envir = .GlobalEnv)), envir = .GlobalEnv)
}

rhtests <- NULL
summary <- NULL
for (i in seq_len(nrow(keys))) {
  s <- data[data$variable == keys$variable[i] & data$series == keys$series[i], ]
  name <- paste(keys$variable[i], keys$series[i], sep = "_")
  base <- file.path(work, paste0(name, ".dat"))
  ref <- file.path(work, paste0(name, "_zero.dat"))
  write_rhtests(base, s, s$value)
  write_rhtests(ref, s, rep(0, nrow(s)))
  for (method in c("PMF", "PMT")) {
    output <- file.path(work, paste0(name, "_", method))
    clear_globals()
    err <- tryCatch({
      res <- capture.output(
        if (method == "PMF") FindU(base, output, MISSING, p.lev = level)
        else FindU.wRef(base, ref, output, MISSING, p.lev = level))
      if (!file.exists(paste0(output, "_1Cs.txt"))) stop(paste(res, collapse = " "))
      msg <- get0("ErrorMSG", envir = .GlobalEnv, ifnotfound = NA)
      if (!is.na(msg)) stop(msg)
      ""
    }, error = function(e) conditionMessage(e))
    if (nzchar(err)) {
      summary <- rbind(summary, data.frame(variable = keys$variable[i],
        series = keys$series[i], method = tolower(method), breaks = NA,
        error = gsub("[\n,]", " ", trimws(err))))
      next
    }
    first <- readLines(paste0(output, "_1Cs.txt"), n = 1)
    ns <- as.integer(sub("^\\s*([0-9]+) changepoints.*", "\\1", first))
    summary <- rbind(summary, data.frame(variable = keys$variable[i],
      series = keys$series[i], method = tolower(method), breaks = ns, error = ""))
    if (ns == 0) next
    cs <- parse_1cs(paste0(output, "_1Cs.txt"))
    st <- parse_ustat(paste0(output, "_Ustat.txt"), method)
    if (nrow(cs) != ns || nrow(st) != ns) stop(paste("unexpected RHtests output for", name))
    rhtests <- rbind(rhtests, data.frame(variable = keys$variable[i],
      series = keys$series[i], method = tolower(method), cs,
      prob = st$prob, cv = st$cv, nseg = st$nseg, step = st$step))
  }
}
cols <- c("variable", "series", "method", "date", "label", "statistic", "cv", "cv_low",
          "cv_high", "prob", "prob_low", "prob_high", "nseg", "step")
if (is.null(rhtests)) rhtests <- setNames(data.frame(matrix(nrow = 0, ncol = length(cols))), cols)
write.csv(rhtests[, cols], file.path(out, "rhtests.csv"), row.names = FALSE, quote = FALSE)
write.csv(summary, file.path(out, "rhtests_series.csv"), row.names = FALSE, quote = FALSE)

set.seed(seed)
write.csv(data.frame(rnorm = num(rnorm(10))), file.path(out, "rnorm.csv"), row.names = FALSE,
          quote = FALSE)
