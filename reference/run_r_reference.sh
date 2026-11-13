#!/usr/bin/env bash
# Build the R reference image and run Climpact v3.4.3 in it.
#
#   ./reference/run_r_reference.sh                  build, then run every station in stations.csv
#   ./reference/run_r_reference.sh lat0 phoenix     build, then run only the named runs
#
# Each row of reference/stations.csv is one run: the input file
# reference/input/<name>_<start>-<end>.txt is run at the row's lat/lon, and the outputs go to
# reference/output/<run>/<name>_<start>-<end>/. The lat0 run also runs Climpact's own CSV test
# (climpact/tests/output_compare) and writes comparison_summary.csv.
#
# Set CLIMPACT_DIR to point at the original Climpact repo (default: ../climpact).
#
# Runs on linux/amd64 by default (emulated on Apple Silicon). The stored reference outputs were
# produced on x86_64; on arm64 the bootstrapped in-base percentiles in climdex.pcic's C++ code
# round differently, which flips threshold ties and changes tx10p, tn10p, tx90p and csdi in some
# base-period years. Set PLATFORM=linux/arm64 to run natively anyway.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CLIMPACT_DIR="${CLIMPACT_DIR:-$(cd "$HERE/../../climpact" && pwd)}"
PLATFORM="${PLATFORM:-linux/amd64}"
IMAGE="climpact-r-ref:3.4.3-${PLATFORM#linux/}"
OUT="$HERE/output"
STATIONS="$HERE/stations.csv"

all_runs=$(tail -n +2 "$STATIONS" | cut -d, -f1)
for r in "$@"; do
  grep -qx "$r" <<<"$all_runs" || { echo "unknown run: $r (see $STATIONS)" >&2; exit 2; }
done
runs=("$@")
[[ ${#runs[@]} -gt 0 ]] || read -r -d '' -a runs <<<"$all_runs" || true

docker build --platform "$PLATFORM" -t "$IMAGE" "$HERE/r"

status=0
for run in "${runs[@]}"; do
  IFS=, read -r _ _ name lat lon start end _ < <(grep "^$run," "$STATIONS")
  station="${name}_${start}-${end}"
  cmd=generate
  [[ "$run" == lat0 ]] && cmd=all
  echo "=== $run: $station at lat $lat lon $lon"
  rm -rf "${OUT:?}/$run"
  mkdir -p "$OUT/$run"
  docker run --rm --platform "$PLATFORM" \
    -v "$CLIMPACT_DIR:/climpact:ro" \
    -v "$HERE/input:/input:ro" \
    -v "$OUT/$run:/out" \
    "$IMAGE" "$cmd" --lat "$lat" --lon "$lon" --station "/input/$station.txt" --name "$station" \
    || { echo "=== $run: R run failed" >&2; status=1; }
  git -C "$CLIMPACT_DIR" rev-parse HEAD > "$OUT/$run/climpact-commit.txt"
  # The plots are gitignored; their names (without the station prefix) are committed, for
  # the plot file-list test.
  if [[ -d "$OUT/$run/$station/plots" ]]; then
    ls "$OUT/$run/$station/plots" | sed "s/^${station}_//" > "$OUT/$run/plot-files.txt"
  fi
done
exit $status
