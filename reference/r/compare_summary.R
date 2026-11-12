# Per-file comparison of generated Climpact outputs against the stored reference.
#
# Unlike tests/output_compare/test_output.R (which only checks the indices/ folder and
# stops at the first unreadable file), this covers indices/, thres/ and trend/, reports
# missing and extra files, and gives the largest numeric difference per file.
#
# Usage: Rscript compare_summary.R EXPECTED_DIR GENERATED_DIR

args <- commandArgs(trailingOnly = TRUE)
expected_dir <- args[1]
generated_dir <- args[2]

meta_pattern <- '^"(Description|Station|Latitude|Longitude|Base_period|Climpact_version|Date_of_calculation): "'

read_body <- function(path) {
  lines <- readLines(path, warn = FALSE)
  lines[!grepl(meta_pattern, lines)]
}

max_numeric_diff <- function(a, b) {
  if (length(a) != length(b)) return(NA_real_)
  fa <- strsplit(a, ",", fixed = TRUE)
  fb <- strsplit(b, ",", fixed = TRUE)
  worst <- 0
  for (k in seq_along(fa)) {
    if (length(fa[[k]]) != length(fb[[k]])) return(NA_real_)
    na <- suppressWarnings(as.numeric(trimws(fa[[k]])))
    nb <- suppressWarnings(as.numeric(trimws(fb[[k]])))
    both <- !is.na(na) & !is.na(nb)
    if (any(is.na(na) != is.na(nb))) return(Inf)  # missing-value pattern differs
    if (any(both)) worst <- max(worst, abs(na[both] - nb[both]))
  }
  worst
}

rows <- list()
for (sub in c("indices", "thres", "trend")) {
  exp_files <- list.files(file.path(expected_dir, sub))
  gen_files <- list.files(file.path(generated_dir, sub), pattern = "\\.csv$")
  for (f in union(exp_files, gen_files)) {
    e <- file.path(expected_dir, sub, f)
    g <- file.path(generated_dir, sub, f)
    status <- if (!file.exists(g)) "missing" else if (!file.exists(e)) "extra" else {
      eb <- read_body(e); gb <- read_body(g)
      if (identical(eb, gb)) "identical" else "different"
    }
    diff_lines <- NA_integer_; max_diff <- NA_real_
    if (status == "different") {
      n <- max(length(eb), length(gb))
      diff_lines <- sum(eb[seq_len(n)] != gb[seq_len(n)], na.rm = TRUE) + abs(length(eb) - length(gb))
      max_diff <- max_numeric_diff(eb, gb)
    }
    rows[[length(rows) + 1]] <- data.frame(folder = sub, file = f, status = status,
                                           differing_lines = diff_lines, max_abs_diff = max_diff)
  }
}
res <- do.call(rbind, rows)
res$file <- sub("^sydney_observatory_hill_1936-2015_", "", res$file)

cat("\n=== Comparison summary ===\n")
print(table(res$folder, res$status))
cat("\n")
not_ok <- res[res$status != "identical", ]
if (nrow(not_ok) > 0) {
  print(not_ok[order(not_ok$folder, not_ok$status, not_ok$file), ], row.names = FALSE)
} else {
  cat("All files identical (ignoring metadata header lines).\n")
}
write.csv(res, file.path(generated_dir, "comparison_summary.csv"), row.names = FALSE)
