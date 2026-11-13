# Prints Climpact's climdex.hwEHF (climpact.etsci-functions.r) for tests/data/ehf_synthetic.txt
# (made by tests/data/make_ehf_synthetic.py), base period 2001-2003, for tests/test_ehf.py; its output is
# stored in tests/data/r_ehf.txt.
# Run in the R reference image (reference/r):
#   docker run --rm --platform linux/amd64 -v $CLIMPACT_DIR:/climpact:ro -v $PWD/packages/climpact/tests/data:/probe:ro \
#     --entrypoint Rscript climpact-r-ref:3.4.3-amd64 /probe/r_ehf.R
# Prints the eight annual aspects (2001-2007), EHF85, and EHF/ECF for the days of
# 2004-11-15 to 2005-01-10. Then runs it again with 28 December 2004 missing, where the
# 2004 piece of the heatwave starting on 1 January has a missing EHF and no positive one.
suppressMessages(library(climdex.pcic))
src <- readLines("/climpact/server/climpact.etsci-functions.r")
a <- grep("^climdex.hwEHF <- function", src)
b <- grep("^# Due seemingly", src) - 1
climdex.hwEHF <- eval(parse(text = src[a:b])[[1]][[3]])

d <- read.table("/probe/ehf_synthetic.txt", col.names = c("y", "m", "d", "prcp", "tmax", "tmin"),
                na.strings = "-99.9")
dates <- as.PCICt(sprintf("%04d-%02d-%02d", d$y, d$m, d$d), cal = "gregorian")
input <- function(tmax, tmin) suppressWarnings(climdexInput.raw(tmax = tmax, tmin = tmin,
  prec = d$prcp, tmax.dates = dates, tmin.dates = dates, prec.dates = dates,
  base.range = c(2001, 2003), northern.hemisphere = FALSE))
fmt <- function(x) ifelse(is.na(x), "NA", sprintf("%.17g", x))

out <- climdex.hwEHF(input(d$tmax, d$tmin), ehfdef = "NF13")
for (k in c("hwps", "hwpi", "hwls", "hwli", "hwd", "hwmd", "hwn", "hwf"))
  cat(k, fmt(out[[k]]), "\n")
cat("ehf85", fmt(unname(out$ehf85)), "\n")
days <- which(as.character(out$hw_dates) >= "2004-11-15" & as.character(out$hw_dates) <= "2005-01-10")
for (i in days) cat("day", as.character(out$hw_dates[i]), fmt(out$EHF_daily_values[i]),
                    fmt(out$ECF_daily_values[i]), "\n")

tmax <- d$tmax; tmin <- d$tmin
gone <- which(as.character(dates) == "2004-12-28")
tmax[gone] <- NA; tmin[gone] <- NA
res <- tryCatch({ climdex.hwEHF(input(tmax, tmin), ehfdef = "NF13"); "no error" },
                error = function(e) conditionMessage(e))
cat("missing-lead-day:", res, "\n")
