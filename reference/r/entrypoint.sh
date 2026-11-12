#!/usr/bin/env bash
# Container entrypoint.
#
# Expects:
#   /climpact  the original Climpact repo, mounted read-only
#   /out       a writable directory for outputs
#
# Commands:
#   generate [run_reference.R args...]  run Climpact headless, outputs to /out
#   test                                run climpact/tests/output_compare/test_output.R on /out
#   compare                             per-file summary of /out against the stored reference
#   all [run_reference.R args...]       generate, then test and compare
set -euo pipefail

STATION=sydney_observatory_hill_1936-2015

# Work on a writable copy: Climpact writes temporary files and Rplots.pdf into its tree.
prepare_workdir() {
  rm -rf /work
  mkdir -p /work
  (cd /climpact && tar --exclude=.git --exclude=www/output -cf - .) | tar -xf - -C /work
  mkdir -p /work/www
  ln -sfn /out /work/www/output   # the test reads ../../www/output/<station>/
}

cmd_generate() {
  cd /work
  Rscript /opt/climpact-ref/run_reference.R --out /out "$@"
  cp /opt/r-package-versions.csv /out/r-package-versions.csv
}

cmd_test() {
  cd /work/tests/output_compare
  Rscript -e '
    library(testthat)
    res <- as.data.frame(test_file("test_output.R", reporter = "summary", stop_on_failure = FALSE))
    cat("\noutput_compare: passed", sum(res$passed), "failed", sum(res$failed),
        "errors", sum(res$error), "\n")
    if (sum(res$failed) > 0 || any(res$error)) quit(status = 1)
  '
}

cmd_compare() {
  Rscript /opt/climpact-ref/compare_summary.R /climpact/tests/output_compare "/out/${STATION}"
}

prepare_workdir
cmd="${1:-all}"
shift || true
case "$cmd" in
  generate) cmd_generate "$@" ;;
  test)     cmd_test ;;
  compare)  cmd_compare ;;
  all)      cmd_generate "$@"; status=0; cmd_test || status=$?; cmd_compare; exit $status ;;
  *)        echo "unknown command: $cmd" >&2; exit 2 ;;
esac
