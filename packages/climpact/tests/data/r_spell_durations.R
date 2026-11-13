# Prints climdex.pcic's select.blocks.gt.length and threshold.exceedance.duration.index and
# Climpact's dual.threshold.exceedance.duration.index on small synthetic series, for
# tests/test_spell_durations.py. Run in the R reference image (reference/r):
#   docker run --rm --platform linux/amd64 -v $CLIMPACT_DIR:/climpact:ro -v $PWD/tests/data:/probe:ro \
#     --entrypoint Rscript climpact-r-ref:3.4.3-amd64 /probe/r_spell_durations.R
# Output (climdex.pcic 1.2-0 with Climpact's dual.threshold.exceedance.duration.index):
#   select n=0 : 1 1 0 1 1 1 0 NA 1 1
#   select n=1 : 1 1 0 1 1 1 0 0 1 1
#   select n=2 : 0 0 0 1 1 1 0 0 0 0
#   select n=10 : 0 0 0 0 0 0 0 0 0 0
#   ted min=1 : NA 3
#   ted min=2 : 16 3
#   ted min=3 : 14 3
#   ted 16 NA : 4 20
#   dual n=1 : 1 3
#   dual n=2 : 1 3
#   dual n=3 : 0 0
#   dual n=2 t2 NA : 0 3
suppressMessages(library(climdex.pcic))
src <- readLines("/climpact/server/climpact.etsci-functions.r")
a <- grep("^dual.threshold.exceedance.duration.index <- function", src)
b <- grep("^# SPEI. From the SPEI", src) - 1
dual <- eval(parse(text = src[a:b])[[1]][[3]])
environment(dual) <- asNamespace("climdex.pcic")
sb <- climdex.pcic:::select.blocks.gt.length
ted <- climdex.pcic:::threshold.exceedance.duration.index
show <- function(label, x) cat(label, ":", paste(ifelse(is.na(x), "NA", as.character(as.numeric(x))), collapse = " "), "\n")

d <- c(TRUE, TRUE, FALSE, TRUE, TRUE, TRUE, FALSE, NA, TRUE, TRUE)
show("select n=0", sb(d, 0))
show("select n=1", sb(d, 1))
show("select n=2", sb(d, 2))
show("select n=10", sb(d, 10))

# Two "years" of 20 days; threshold 0 everywhere.
f <- factor(rep(c("y1", "y2"), each = 20))
jd <- rep(1:20, 2)
x <- c(1, 1, 1, -1, 1, 1, NA, 1, 1, 1, 1, 1, 1, -1, -1, 1, 1, 1, 1, 1,
       -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, 1, 1, 1)
show("ted min=1", ted(x, f, jd, rep(0, 20), ">", 1, FALSE, 15))
show("ted min=2", ted(x, f, jd, rep(0, 20), ">", 2, FALSE, 15))
show("ted min=3", ted(x, f, jd, rep(0, 20), ">", 3, FALSE, 15))
# 16 missing days in a year: R's own 15-day mask does not apply (always 1).
x2 <- c(rep(NA, 16), 1, 1, 1, 1, rep(1, 20))
show("ted 16 NA", ted(x2, f, jd, rep(0, 20), ">", 2, FALSE, 15))

# Dual threshold: y1 has a 2-day event, a 3-day event, then a 3-day event 3 days later
# (merged); y2 has two 3-day events 4 days apart, and an NA inside a run.
t1 <- c(1, 1, -1, -1, -1, 1, 1, 1, -1, -1, -1, 1, 1, 1, -1, -1, -1, -1, -1, -1,
        1, 1, 1, -1, -1, -1, -1, 1, 1, 1, -1, -1, -1, -1, -1, 1, NA, 1, 1, 1)
t2 <- rep(1, 40)
show("dual n=1", dual(t1, t2, f, jd, rep(0, 20), rep(0, 20), ">", ">", 1, 15))
show("dual n=2", dual(t1, t2, f, jd, rep(0, 20), rep(0, 20), ">", ">", 2, 15))
show("dual n=3", dual(t1, t2, f, jd, rep(0, 20), rep(0, 20), ">", ">", 3, 15))
show("dual n=2 t2 NA", dual(t1, c(rep(NA, 20), rep(1, 20)), f, jd, rep(0, 20), rep(0, 20), ">", ">", 2, 15))
