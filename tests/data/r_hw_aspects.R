# Prints Climpact's get.hw.aspects (climpact.etsci-functions.r) on small synthetic series,
# for tests/test_heatwaves.py. Run in the R reference image (reference/r):
#   docker run --rm --platform linux/amd64 -v $CLIMPACT_DIR:/climpact:ro -v $PWD/tests/data:/probe:ro \
#     --entrypoint Rscript climpact-r-ref:3.4.3-amd64 /probe/r_hw_aspects.R
# Rows are HWM, HWA, HWN, HWD, HWF; columns are the years 2001-2003. The output is copied
# into tests/test_heatwaves.py, except the whole-season heatwave (north 2002) and the series
# with no heatwave, where Python deliberately differs from R (#51).
suppressMessages(library(climdex.pcic))
src <- readLines("/climpact/server/climpact.etsci-functions.r")
a <- grep("^get.hw.aspects <- function", src)
b <- grep("^# climdex.hwEHF$", src) - 1
get.hw.aspects <- eval(parse(text = src[a:b])[[1]][[3]])

dates <- seq(as.Date("2001-01-01"), as.Date("2003-12-31"), by = "day")
years <- factor(format(dates, "%Y"))
months <- factor(format(dates, "%Y-%m"))
i <- seq_along(dates)
base.data <- (200 + (i * 37) %% 101) / 10
set <- function(x, from, to, value) { x[dates >= as.Date(from) & dates <= as.Date(to)] <- value; x }

show <- function(label, flags, data, northern, namask = 1) {
  out <- get.hw.aspects(array(NA, c(5, 3)), flags, years, months, data, northern, namask)
  for (r in 1:5) cat(label, r, ":", paste(ifelse(is.na(out[r, ]), "NA", format(out[r, ], digits = 17)), collapse = " "), "\n")
}

# Northern Hemisphere (May-Sep).
f <- rep(FALSE, length(dates)); d <- base.data
f <- set(f, "2001-04-29", "2001-05-02", TRUE)  # began before the season, 2 days inside
f <- set(f, "2001-06-10", "2001-06-12", TRUE); d <- set(d, "2001-06-10", "2001-06-12", c(30, 31, 32))
f <- set(f, "2001-07-01", "2001-07-03", TRUE); d <- set(d, "2001-07-01", "2001-07-03", 31)  # same mean
f <- set(f, "2001-09-20", "2001-10-31", TRUE)  # runs past the season: cut 14 days after it
f <- set(f, "2002-04-20", "2002-10-10", TRUE)  # covers the whole season: not counted (Python counts it, #51)
f <- set(f, "2003-04-28", "2003-05-01", TRUE)  # began before the season, 1 day inside
f <- set(f, "2003-08-01", "2003-08-08", TRUE); f <- set(f, "2003-08-04", "2003-08-04", NA)
d <- set(d, "2003-08-06", "2003-08-06", NA)
show("north", f, d, TRUE)

# Southern Hemisphere (Nov-Mar), with a missing year in the mask.
f <- rep(FALSE, length(dates)); d <- base.data
f <- set(f, "2001-12-29", "2002-01-03", TRUE)  # crosses the year boundary
f <- set(f, "2002-03-28", "2002-04-20", TRUE)  # runs past the season: cut 14 days after it
f <- set(f, "2002-11-05", "2002-11-07", TRUE)
show("south", f, d, FALSE, c(1, 1, NA))

# No heatwave at all: HWN and HWF are missing too (Python gives 0, #51).
show("none", rep(FALSE, length(dates)), base.data, TRUE)
