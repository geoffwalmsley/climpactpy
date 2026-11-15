#!/bin/sh
# Build climpact-web's stylesheet with the pinned standalone Tailwind CLI (#118).
#
#   scripts/build-css.sh           # build static/climpact_web/css/climpact.css once
#   scripts/build-css.sh --watch   # rebuild whenever a template, script or source changes
#
# The CLI comes from scripts/fetch-tailwind.sh (bin/tailwindcss, or TAILWIND_BIN). The
# output is committed; CI rebuilds it and fails if it differs.
set -eu

root=$(cd "$(dirname "$0")/.." && pwd)
core=$root/packages/climpact-web/src/climpact_web/core
tailwind=${TAILWIND_BIN:-$root/bin/tailwindcss}

if [ ! -x "$tailwind" ]; then
    echo "build-css: no Tailwind CLI at $tailwind; run scripts/fetch-tailwind.sh first" >&2
    exit 1
fi

cd "$core/tailwind"
exec "$tailwind" --input climpact.css --output ../static/climpact_web/css/climpact.css --minify "$@"
