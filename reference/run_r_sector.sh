#!/usr/bin/env bash
# Build the R reference image and run Climpact's sector correlation (server/sector_correlation.R)
# on the committed sydney run, with Climpact's sample sector file, detrended and not.
#
#   ./reference/run_r_sector.sh
#
# Inputs: the raw station file reference/input/sydney_observatory_hill_1936-2015.txt, the index
# CSVs committed in reference/output/sydney/<station>/indices, and
# reference/input/sector/wheat_yield_nsw_1922-1999.csv (a copy of Climpact's
# www/sample_data file). Outputs go to reference/output/sydney/sector/{detrended,raw}/ (the
# app's corr/ folder). The PNGs are gitignored; the CSVs are committed.
#
# CLIMPACT_DIR and PLATFORM as for run_r_reference.sh.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CLIMPACT_DIR="${CLIMPACT_DIR:-$(cd "$HERE/../../climpact" && pwd)}"
PLATFORM="${PLATFORM:-linux/amd64}"
IMAGE="climpact-r-ref:3.4.3-${PLATFORM#linux/}"
STATION=sydney_observatory_hill_1936-2015
SECTOR=wheat_yield_nsw_1922-1999.csv
OUT="$HERE/output/sydney/sector"

docker build --platform "$PLATFORM" -t "$IMAGE" "$HERE/r"

rm -rf "$OUT"
for mode in detrended raw; do
  detrend=TRUE
  [[ $mode == raw ]] && detrend=FALSE
  mkdir -p "$OUT/$mode"
  echo "=== sydney sector correlation: $mode"
  docker run --rm --platform "$PLATFORM" \
    -v "$CLIMPACT_DIR:/climpact:ro" \
    -v "$HERE/input:/input:ro" \
    -v "$HERE/output/sydney/$STATION/indices:/indices:ro" \
    -v "$OUT/$mode:/out" \
    "$IMAGE" sector-correlation --station "/input/$STATION.txt" --sector "/input/sector/$SECTOR" \
    --indices /indices --out /out --name "$STATION" --detrend "$detrend"
done
docker run --rm --platform "$PLATFORM" --entrypoint cat "$IMAGE" /opt/r-package-versions.csv \
  > "$OUT/r-package-versions.csv"
git -C "$CLIMPACT_DIR" rev-parse HEAD > "$OUT/climpact-commit.txt"
