# Headless run of climpact.ncdf.wrapper.r on a given grid.
#
# The wrapper is a script with its settings hard-coded at the top; this makes the same
# call, create.indices.from.files() from Climpact's modified climdex.pcic.ncdf, with the
# wrapper's fixed settings (cores = FALSE, indices = NULL, EHF_DEF = "NF13",
# axis.name = "Y", maxvals = 10, fclimdex.compatible = FALSE, the custom index settings
# wsdin_n = csdin_n = 5, hddheatn_n = cddcoldn_n = 18, gddgrown_n = 10, rxnday_n = 7,
# rnnmm_n = 30, ntxntn_n = ntxbntnb_n = 3, project.lat2d.coords = TRUE and its
# thresholds.name.map) and the input files, variable names, output template, base
# period, thresholds file and author data given as arguments.
#
# Usage (run from the root of a writable copy of the climpact repo):
#   Rscript run_gridded_indices.R --files a.nc[,b.nc] --outdir dir [--template var_daily_m_e_r_1966-2005.nc] \
#     [--tmax tasmax] [--tmin tasmin] [--prec pr] [--base_start 1971] [--base_end 2000] \
#     [--thresholds thresholds.nc] [--exclude hw,hwEHF] [--indices hw,hwEHF,spi,spei]
#
# --exclude leaves indices out (climdex.vars.subset is every other index of
# server/climate.indices.csv): R stops in write.climdex.results on the hw and hwEHF
# files of any grid with an all-missing cell. --indices computes only those indices
# (climdex.vars.subset, less any excluded).

suppressPackageStartupMessages(library(climdex.pcic.ncdf))

args <- commandArgs(trailingOnly = TRUE)
opt <- list(files = NULL, outdir = NULL, template = "", tmax = "tasmax", tmin = "tasmin",
            prec = "pr", base_start = 1971, base_end = 2000, thresholds = "", exclude = "", indices = "",
            institution = "climpactpy reference", institution_id = "CPY")
i <- 1
while (i <= length(args)) {
  key <- gsub("-", "_", sub("^--", "", args[i]))
  if (!key %in% names(opt)) stop("Unknown argument: ", args[i])
  opt[[key]] <- args[i + 1]
  i <- i + 2
}
if (is.null(opt$files) || is.null(opt$outdir)) stop("--files and --outdir are required")

infiles <- strsplit(opt$files, ",")[[1]]
# The output names follow the template (CMIP5 naming); by default the years of the data.
if (!nzchar(opt$template)) {
  nc <- ncdf4::nc_open(infiles[1])
  years <- range(as.numeric(format(ncdf4.helpers::nc.get.time.series(nc), "%Y")))
  ncdf4::nc_close(nc)
  opt$template <- sprintf("var_daily_climpactpy_historical_NA_%d-%d.nc", years[1], years[2])
}
vars <- c(prec = opt$prec, tmax = opt$tmax, tmin = opt$tmin)
base.range <- c(as.numeric(opt$base_start), as.numeric(opt$base_end))
author.data <- list(institution = opt$institution, institution_id = opt$institution_id)
subset <- NULL
if (nzchar(opt$exclude) || nzchar(opt$indices)) {
  subset <- unique(read.csv("server/climate.indices.csv", sep = "\t", stringsAsFactors = FALSE)$Short.name)
  if (nzchar(opt$indices)) subset <- intersect(subset, strsplit(opt$indices, ",")[[1]])
  subset <- setdiff(subset, strsplit(opt$exclude, ",")[[1]])
}
thresholds.files <- if (nzchar(opt$thresholds)) opt$thresholds else NULL

cat("Climpact gridded indices:", infiles, "base", base.range, "thresholds", opt$thresholds, "\n")
create.indices.from.files(infiles, opt$outdir, opt$template, author.data, variable.name.map = vars,
  base.range = base.range, parallel = FALSE, axis.to.split.on = "Y", climdex.vars.subset = subset,
  thresholds.files = thresholds.files, fclimdex.compatible = FALSE, root.dir = getwd(),
  cluster.type = "SOCK", ehfdef = "NF13", max.vals.millions = 10, wsdin_n = 5, csdin_n = 5,
  hddheatn_n = 18, cddcoldn_n = 18, gddgrown_n = 10, rxnday_n = 7, rnnmm_n = 30, ntxntn_n = 3,
  ntxbntnb_n = 3, project.lat2d.coords = TRUE,
  thresholds.name.map = c(tx05thresh = "tx05thresh", tx10thresh = "tx10thresh", tx50thresh = "tx50thresh",
    tx90thresh = "tx90thresh", tx95thresh = "tx95thresh", tn05thresh = "tn05thresh", tn10thresh = "tn10thresh",
    tn50thresh = "tn50thresh", tn90thresh = "tn90thresh", tn95thresh = "tn95thresh",
    tx90thresh_15days = "tx90thresh_15days", tn90thresh_15days = "tn90thresh_15days",
    tavg90thresh_15days = "tavg90thresh_15days", tavg05thresh = "tavg05thresh", tavg95thresh = "tavg95thresh",
    ehf85thresh = "ehf85thresh", txraw = "txraw", tnraw = "tnraw", precraw = "precraw",
    r95thresh = "r95thresh", r99thresh = "r99thresh"))
