#!/usr/bin/env bash
# Build the R reference image and run Climpact's gridded thresholds
# (climpact.ncdf.thresholds.wrapper.r) and gridded indices (climpact.ncdf.wrapper.r) on the
# test grids.
#
#   ./reference/run_r_gridded.sh                 build, then run every grid in gridded/runs.csv
#   ./reference/run_r_gridded.sh grid_sample     build, then run only the named runs
#
# Each row of reference/gridded/runs.csv is one run: the input files (';'-separated, in
# reference/gridded/input/, made by gridded/make_grids.py), the netCDF variable names, the
# base period, whether to compute a thresholds file, the run whose thresholds file the
# indices use (empty: none, R computes the thresholds itself), the indices to leave out
# (';'-separated; R stops on hw and hwEHF for grids with an all-missing cell) and the
# indices to compute (';'-separated; empty: all but the excluded ones).
#
# Outputs go to reference/gridded/output/<run>/: thresholds.nc and indices/<index>_<freq>_*.nc,
# compressed afterwards with nccopy (lossless: same variables, values and attributes; only
# the chunking and compression change). Runs that use another run's thresholds come after it
# in runs.csv.
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
  IFS=, read -r _ files tmax tmin prec base_start base_end thresholds indices_thresholds exclude only \
    < <(grep "^$run," "$RUNS")
  out="$GRID/output/$run"
  rm -rf "$out"
  mkdir -p "$out"
  inputs=$(tr ';' '\n' <<<"$files" | sed 's#^#/input/#' | paste -sd, -)
  thr_arg=""
  [[ -z "$indices_thresholds" ]] || thr_arg="--thresholds /output/$indices_thresholds/thresholds.nc"
  echo "=== $run: $inputs, base $base_start-$base_end"
  script="set -e"
  if [[ "$thresholds" == yes ]]; then
    script+="
      /opt/climpact-ref/entrypoint.sh gridded-thresholds --files '$inputs' --out /tmp/thresholds.nc \
        --tmax '$tmax' --tmin '$tmin' --prec '$prec' --base_start '$base_start' --base_end '$base_end'
      nccopy -d 9 -s -c time/365,base_time/11000 /tmp/thresholds.nc /out/thresholds.nc"
  fi
  script+="
    /opt/climpact-ref/entrypoint.sh gridded-indices --files '$inputs' --outdir /tmp/indices \
      --tmax '$tmax' --tmin '$tmin' --prec '$prec' --base_start '$base_start' --base_end '$base_end' \
      --exclude '${exclude//;/,}' --indices '${only//;/,}' $thr_arg
    mkdir -p /out/indices
    for f in /tmp/indices/*.nc; do nccopy -d 9 -s -c time/365 \"\$f\" \"/out/indices/\$(basename \"\$f\")\"; done
    cp /opt/r-package-versions.csv /out/r-package-versions.csv"
  docker run --rm --platform "$PLATFORM" \
    -v "$CLIMPACT_DIR:/climpact:ro" \
    -v "$GRID/input:/input:ro" \
    -v "$GRID/output:/output:ro" \
    -v "$out:/out" \
    --entrypoint bash "$IMAGE" -c "$script" \
    || { echo "=== $run: R run failed" >&2; status=1; }
  git -C "$CLIMPACT_DIR" rev-parse HEAD > "$out/climpact-commit.txt"
done
exit $status
