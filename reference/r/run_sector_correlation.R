# Headless run of Climpact's sector correlation step (server/sector_correlation.R), as the
# Shiny app's step 4 (modules/singleStationStep4.R) calls it after an index run.
#
# Usage (run from the root of a writable copy of the climpact repo):
#   Rscript run_sector_correlation.R --station FILE --sector FILE --indices DIR --out DIR \
#     --name NAME [--title TITLE] [--ylabel LABEL] [--detrend TRUE]
#
# --station is the raw station file loaded at step 1 (R reads it again, unchecked), --indices
# the folder of index CSVs written at step 3. As the app: the title defaults to the station
# name, the y-axis label to the sector file name up to its first '_' or '.', and detrending
# is on.

args <- commandArgs(trailingOnly = TRUE)
opt <- list(station = NULL, sector = NULL, indices = NULL, out = NULL, name = NULL,
            title = NULL, ylabel = NULL, detrend = "TRUE")
i <- 1
while (i <= length(args)) {
  key <- gsub("-", "_", sub("^--", "", args[i]))
  if (!key %in% names(opt)) stop("Unknown argument: ", args[i])
  opt[[key]] <- args[i + 1]
  i <- i + 2
}
for (k in c("station", "sector", "indices", "out", "name")) {
  if (is.null(opt[[k]])) stop("--", k, " is required")
}
if (is.null(opt$title)) opt$title <- opt$name
if (is.null(opt$ylabel)) opt$ylabel <- strsplit(basename(opt$sector), "[_\\.]")[[1]][1]

suppressPackageStartupMessages({
  library(dplyr)
  library(ggplot2)
})
source("server/climpact.GUI-functions.r")
source("server/climpact.etsci-functions.r")
source("server/global_variables.r")
source("server/sector_correlation.R")

# shiny::Progress stand-in
progress <- list(inc = function(...) invisible(NULL))

dir.create(opt$out, showWarnings = FALSE, recursive = TRUE)
error <- draw.correlation(progress, opt$station, opt$sector, opt$name, opt$title,
                          as.logical(opt$detrend), opt$ylabel, opt$out, opt$indices)
if (error != "") stop(error)
cat("Done. Outputs in", opt$out, "\n")
