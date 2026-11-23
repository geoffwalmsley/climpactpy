#!/usr/bin/env bash
# Reference results for the homogeneity break detection (#34): build the R reference image,
# write the tested series with the Python code, then run trend::pettitt.test, trend::snh.test
# (with binary segmentation) and RHtestsV4's FindU (PMFred) and FindU.wRef (PMTred) on them.
#
#   ./reference/run_r_homogeneity.sh                 every station of homogeneity/series
#   ./reference/run_r_homogeneity.sh potsdam sydney  only the named runs
#
# Inputs: reference/homogeneity/series/<run>.csv, written by homogeneity/make_series.py
# from the station files in reference/input. Outputs go to reference/homogeneity/output/<run>/
# (tests.csv, rhtests.csv, rhtests_series.csv, rnorm.csv), with r-package-versions.csv and
# rhtests-commit.txt in reference/homogeneity/output/.
#
# CLIMPACT_DIR and PLATFORM as for run_r_reference.sh (the container's entrypoint copies the
# Climpact repo, although these tests do not use it).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CLIMPACT_DIR="${CLIMPACT_DIR:-$(cd "$HERE/../../climpact" && pwd)}"
PLATFORM="${PLATFORM:-linux/amd64}"
IMAGE="climpact-r-ref:3.4.3-${PLATFORM#linux/}"
SERIES="$HERE/homogeneity/series"
OUT="$HERE/homogeneity/output"

docker build --platform "$PLATFORM" -t "$IMAGE" "$HERE/r"
(cd "$HERE/.." && uv run python reference/homogeneity/make_series.py "$@")

runs=("$@")
if [[ ${#runs[@]} -eq 0 ]]; then
  runs=()
  for f in "$SERIES"/*.csv; do runs+=("$(basename "$f" .csv)"); done
fi

status=0
for run in "${runs[@]}"; do
  [[ -f "$SERIES/$run.csv" ]] || { echo "unknown run: $run (no $SERIES/$run.csv)" >&2; exit 2; }
  echo "=== homogeneity: $run"
  rm -rf "${OUT:?}/$run"
  mkdir -p "$OUT/$run"
  docker run --rm --platform "$PLATFORM" \
    -v "$CLIMPACT_DIR:/climpact:ro" \
    -v "$SERIES:/series:ro" \
    -v "$OUT/$run:/out" \
    "$IMAGE" homogeneity --series "/series/$run.csv" --out /out \
    || { echo "=== $run: R run failed" >&2; status=1; }
done
docker run --rm --platform "$PLATFORM" --entrypoint cat "$IMAGE" /opt/r-package-versions.csv \
  > "$OUT/r-package-versions.csv"
docker run --rm --platform "$PLATFORM" --entrypoint cat "$IMAGE" /opt/rhtests/commit.txt \
  > "$OUT/rhtests-commit.txt"
exit $status
