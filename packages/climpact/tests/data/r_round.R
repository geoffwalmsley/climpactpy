# Prints R's abs(round(diff(x), digits = 1)), the day-to-day change the QC jump and
# flatline checks use (services/check/jumps_tx.R ...), for tests/test_qc.py; the output
# is stored in tests/data/r_round.txt as C99 hex floats: one "change rounded" pair a line.
# Run in the R reference image (reference/r):
#   docker run --rm --platform linux/amd64 -v $PWD/packages/climpact/tests/data:/probe:ro \
#     --entrypoint Rscript climpact-r-ref:3.4.3-amd64 /probe/r_round.R > packages/climpact/tests/data/r_round.txt
# Cases: changes between values with two decimals and with one decimal (uniform in
# [-60, 60]), and changes that sit on or next to a rounding tie.
set.seed(25)
x <- c(round(runif(400, -60, 60), 2), round(runif(400, -60, 60), 1))
d <- c(diff(x), 20.05, 0.15, 0.25, 0.45, -0.15, 2.675, 1.005, 19.95, 20.000000000000004,
       30.05 - 10.1, 30.1 - 10.05, 21.3 - 1.25, 0, -0)
cat(sprintf("%a %a\n", d, abs(round(d, digits = 1))), sep = "")
