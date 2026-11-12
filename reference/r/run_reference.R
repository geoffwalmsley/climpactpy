# Headless Climpact run that reproduces the Shiny single-station workflow.
#
# The parameter defaults are the Shiny UI defaults (modules/singleStation*UI.R), which are
# what the stored reference outputs in climpact/tests/output_compare were generated with:
# latitude 0, longitude 0, base period 1971-2000, default QC thresholds, default user
# parameters, and the default custom index TN > 0.
#
# Usage (run from the root of a writable copy of the climpact repo):
#   Rscript run_reference.R --out DIR [--lat 0] [--lon 0] [--station FILE] [--name NAME]

args <- commandArgs(trailingOnly = TRUE)
opt <- list(
  out = NULL,
  lat = 0,
  lon = 0,
  station = "www/sample_data/sydney_observatory_hill_1936-2015.txt",
  name = "sydney_observatory_hill_1936-2015",
  base_start = 1971,
  base_end = 2000
)
i <- 1
while (i <= length(args)) {
  key <- sub("^--", "", args[i])
  key <- gsub("-", "_", key)
  if (!key %in% names(opt)) stop("Unknown argument: ", args[i])
  opt[[key]] <- args[i + 1]
  i <- i + 2
}
if (is.null(opt$out)) stop("--out is required")
lat <- as.numeric(opt$lat)
lon <- as.numeric(opt$lon)

# Libraries loaded by app.R that the calculation code relies on (UI-only packages omitted).
# dplyr is kept because app.R attaches it, which changes name masking (e.g. filter, lag).
suppressPackageStartupMessages({
  library(zoo)
  library(zyp)
  library(parallel)
  library(dplyr)
  library(qpdf)
})

# Same source order as app.R followed by server/server.R.
source("server/climpact.GUI-functions.r")
source("server/climpact.etsci-functions.r")
source("models/errors.R")
source("models/climdexInputParams.R")
source("server/global_variables.r")
source("models/outputFolders.R")
source("server/climpact.GUI-functions.r")
source("services/quality_control_checks.R")
source("services/calculate_indices.R")

cat("Climpact version:", software_id, "\n")
cat("Station:", opt$name, " lat:", lat, " lon:", lon, " base:", opt$base_start, "-", opt$base_end, "\n")

# The QC step writes a '.temporary' file next to the input, so work on a copy
# (the Shiny app also works on an uploaded temp copy).
tmp_input <- file.path(tempdir(), basename(opt$station))
file.copy(opt$station, tmp_input, overwrite = TRUE)

folders <- outputFolders(opt$out, opt$name)

qc <- load_data_qc(NULL, 1, tmp_input, lat, lon, opt$name,
                   as.numeric(opt$base_start), as.numeric(opt$base_end), folders,
                   iqr_threshold_temp = 3, iqr_threshold_prec = 5, prec_threshold = 200,
                   temp_threshold = 50, no_variability_threshold = 5, temp_change_threshold = 20)

if (!is.null(qc$warnings) && qc$warnings != "") cat("QC warnings:", qc$warnings, "\n")
if (!is.null(qc$errors) && qc$errors != "") stop("QC errors: ", qc$errors)

params <- climdexInputParams(wsdi_ud = 1, csdi_ud = 1, rx_ud = 3, txtn_ud = 2,
                             Tb_HDD = 18, Tb_CDD = 18, Tb_GDD = 10,
                             rnnmm_ud = 30, custom_SPEI = 24,
                             var.choice = "TN", op.choice = ">", constant.choice = 0)

index.calc(NULL, 2, qc$metadata, qc$cio, folders, params)

cat("Done. Outputs in", folders$outputdir, "\n")
