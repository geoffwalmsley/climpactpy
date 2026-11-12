#!/usr/bin/env bash
# Build the R reference image and run Climpact v3.4.3 in it.
#
#   ./reference/run_r_reference.sh            build, then run both reference sets
#   ./reference/run_r_reference.sh lat0       latitude 0 (matches the stored reference) + R tests
#   ./reference/run_r_reference.sh sydney     Sydney's real coordinates (-33.86, 151.21)
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

docker build --platform "$PLATFORM" -t "$IMAGE" "$HERE/r"

run() {
  local name=$1; shift
  rm -rf "${OUT:?}/$name"
  mkdir -p "$OUT/$name"
  docker run --rm --platform "$PLATFORM" \
    -v "$CLIMPACT_DIR:/climpact:ro" \
    -v "$OUT/$name:/out" \
    "$IMAGE" "$@"
  git -C "$CLIMPACT_DIR" rev-parse HEAD > "$OUT/$name/climpact-commit.txt"
}

target="${1:-both}"
status=0
if [[ "$target" == lat0 || "$target" == both ]]; then
  run lat0 all --lat 0 --lon 0 || status=$?
fi
if [[ "$target" == sydney || "$target" == both ]]; then
  run sydney generate --lat -33.86 --lon 151.21 || status=$?
fi
exit $status
