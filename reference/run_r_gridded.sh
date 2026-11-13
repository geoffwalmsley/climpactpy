#!/usr/bin/env bash
# Build the R reference image and run Climpact's gridded thresholds
# (climpact.ncdf.thresholds.wrapper.r) on the test grids.
#
#   ./reference/run_r_gridded.sh                 build, then run every grid in gridded/runs.csv
#   ./reference/run_r_gridded.sh grid_sample     build, then run only the named runs
#
# Each row of reference/gridded/runs.csv is one run: the input files (';'-separated, in
# reference/gridded/input/, made by gridded/make_grids.py), the netCDF variable names and
# the base period. The thresholds file goes to reference/gridded/output/<run>/thresholds.nc,
# compressed afterwards with nccopy (lossless: same variables, values and attributes; only
# the chunking and compression change).
#
# CLIMPACT_DIR and PLATFORM as for run_r_reference.sh.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CLIMPACT_DIR="${CLIMPACT_DIR:-$(cd "$HERE/../../climpact" && pwd)}"
PLATFORM="${PLATFORM:-linux/amd64}"
IMAGE="climpact-r-ref:3.4.3-${PLATFORM#linux/}"
GRID="$HERE/gridded"
RUNS="$GRID/runs.csv"

all_runs=$(tail -n +2 "$RUNS" | cut -d, -f1)
for r in "$@"; do
  grep -qx "$r" <<<"$all_runs" || { echo "unknown run: $r (see $RUNS)" >&2; exit 2; }
done
runs=("$@")
[[ ${#runs[@]} -gt 0 ]] || read -r -d '' -a runs <<<"$all_runs" || true

docker build --platform "$PLATFORM" -t "$IMAGE" "$HERE/r"

status=0
for run in "${runs[@]}"; do
  IFS=, read -r _ files tmax tmin prec base_start base_end < <(grep "^$run," "$RUNS")
  out="$GRID/output/$run"
  rm -rf "$out"
  mkdir -p "$out"
  inputs=$(tr ';' '\n' <<<"$files" | sed 's#^#/input/#' | paste -sd, -)
  echo "=== $run: $inputs, base $base_start-$base_end"
  docker run --rm --platform "$PLATFORM" \
    -v "$CLIMPACT_DIR:/climpact:ro" \
    -v "$GRID/input:/input:ro" \
    -v "$out:/out" \
    --entrypoint bash "$IMAGE" -c "
      /opt/climpact-ref/entrypoint.sh gridded-thresholds --files '$inputs' --out /tmp/thresholds.nc \
        --tmax '$tmax' --tmin '$tmin' --prec '$prec' --base_start '$base_start' --base_end '$base_end' \
      && nccopy -d 9 -s -c time/365,base_time/11000 /tmp/thresholds.nc /out/thresholds.nc \
      && cp /opt/r-package-versions.csv /out/r-package-versions.csv" \
    || { echo "=== $run: R run failed" >&2; status=1; }
  git -C "$CLIMPACT_DIR" rev-parse HEAD > "$out/climpact-commit.txt"
done
exit $status
