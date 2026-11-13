# Headless run of climpact.ncdf.thresholds.wrapper.r on a given grid.
#
# The wrapper is a script with its settings hard-coded at the top; this makes the same
# call, create.thresholds.from.file() from Climpact's modified climdex.pcic.ncdf, with the
# wrapper's fixed settings (fclimdex.compatible = FALSE, no cluster) and the input files,
# variable names, base period and author data given as arguments.
#
# Usage (run from the root of a writable copy of the climpact repo):
#   Rscript run_gridded_thresholds.R --files a.nc[,b.nc] --out thresholds.nc \
#     [--tmax tasmax] [--tmin tasmin] [--prec pr] [--base_start 1971] [--base_end 2000]

suppressPackageStartupMessages(library(climdex.pcic.ncdf))

args <- commandArgs(trailingOnly = TRUE)
opt <- list(files = NULL, out = NULL, tmax = "tasmax", tmin = "tasmin", prec = "pr",
            base_start = 1971, base_end = 2000,
            institution = "climpactpy reference", institution_id = "CPY")
i <- 1
while (i <= length(args)) {
  key <- gsub("-", "_", sub("^--", "", args[i]))
  if (!key %in% names(opt)) stop("Unknown argument: ", args[i])
  opt[[key]] <- args[i + 1]
  i <- i + 2
}
if (is.null(opt$files) || is.null(opt$out)) stop("--files and --out are required")

input.files <- strsplit(opt$files, ",")[[1]]
vars <- c(tmax = opt$tmax, tmin = opt$tmin, prec = opt$prec)
base.range <- c(as.numeric(opt$base_start), as.numeric(opt$base_end))
author.data <- list(institution = opt$institution, institution_id = opt$institution_id)

cat("Climpact gridded thresholds:", input.files, "base", base.range, "\n")
create.thresholds.from.file(input.files, opt$out, author.data, variable.name.map = vars,
                            base.range = base.range, parallel = FALSE, verbose = TRUE,
                            fclimdex.compatible = FALSE, root.dir = getwd())
