# Prints R's qnorm, pnorm and pgamma for tests/test_rdist.py (values as C99 hex floats).
# Run in the reference image:
#   docker run --rm --platform linux/amd64 -v "$PWD/packages/climpact/tests/data:/data" --entrypoint Rscript \
#     climpact-r-ref:3.4.3-amd64 /data/r_rdist.R > packages/climpact/tests/data/r_rdist.txt
set.seed(1)
p <- c(runif(400), 10^-runif(200, 0, 300), 1 - 10^-runif(100, 1, 16), 0.075, 0.925, 0.5,
       exp(-25), 1 - exp(-25), 1e-300)
x <- c(rnorm(400), runif(200, -40, 40), runif(100, -6, 6), 0.67448975, -0.67448975,
       5.656854249492380195, -5.656854249492380195, 1e-17, 0)
shape <- c(runif(300, 0.05, 50), runif(100, 50, 500))
q <- shape * exp(rnorm(400, 0, 0.8))
for (i in seq_along(p)) cat("qnorm", sprintf("%a", p[i]), sprintf("%a", qnorm(p[i])), "\n")
for (i in seq_along(x)) cat("pnorm", sprintf("%a", x[i]), sprintf("%a", pnorm(x[i])), "\n")
for (i in seq_along(q)) cat("pgamma", sprintf("%a", q[i]), sprintf("%a", shape[i]),
                            sprintf("%a", pgamma(q[i], shape[i])), "\n")
