#!/usr/bin/env bash
# Install the built wheels in a clean virtualenv and smoke-test them (#131):
#
#   scripts/smoke_dists.sh DIST_DIR [PYTHON]
#
# DIST_DIR holds the climpact and climpact-web wheels (uv build --all-packages -o DIST_DIR);
# PYTHON is the interpreter for the virtualenv (default 3.12). The wheels are installed
# from DIST_DIR with their third-party dependencies from PyPI, outside the workspace, so
# nothing comes from the source tree. Checks `climpact --version` and that climpact-web
# imports, starts (migrations, static files, worker) and answers /healthz. CI's `dist` job
# and release.yml run it.
set -euo pipefail

dist=$(cd "${1:?usage: scripts/smoke_dists.sh DIST_DIR [PYTHON]}" && pwd)
python=${2:-3.12}
work=$(mktemp -d)
server=""
cleanup() {
  if [ -n "$server" ]; then kill "$server" 2>/dev/null || true; wait "$server" 2>/dev/null || true; fi
  rm -rf "$work"
}
trap cleanup EXIT

core=$(ls "$dist"/climpact-*-py3-none-any.whl)
web=$(ls "$dist"/climpact_web-*-py3-none-any.whl)
version=$(basename "$core" | cut -d- -f2)

cd "$work"  # away from the checkout, so nothing is imported from it
uv venv --quiet --no-project --python "$python" venv
# --find-links: climpact-web's pin climpact[plots]==VERSION resolves to the local wheel.
VIRTUAL_ENV="$work/venv" uv pip install --quiet --no-config --find-links "$dist" \
  "${core}[plots]" "$web"
bin="$work/venv/bin"

echo "--- climpact --version"
out=$("$bin/climpact" --version)
echo "$out"
case "$out" in
  "Climpact for Python $version (port of Climpact "*) ;;
  *) echo "unexpected: $out (expected Climpact for Python $version ...)" >&2; exit 1 ;;
esac

echo "--- imports"
"$bin/python" -I -c "
import climpact, climpact_web, climpact.plots, climpact.report
from importlib.metadata import version
assert climpact.__version__ == climpact_web.__version__ == version('climpact') == version('climpact-web') == '$version'
print('climpact', climpact.__file__)
print('climpact_web', climpact_web.__file__)
"
"$bin/climpact-web" --version

echo "--- climpact-web serves /healthz"
port=$("$bin/python" -I -c "import socket; s=socket.socket(); s.bind(('127.0.0.1', 0)); print(s.getsockname()[1])")
"$bin/climpact-web" --no-browser --port "$port" --data-dir "$work/data" > "$work/server.log" 2>&1 &
server=$!
for _ in $(seq 1 60); do
  if body=$(curl -fsS "http://127.0.0.1:$port/healthz" 2>/dev/null); then break; fi
  if ! kill -0 "$server" 2>/dev/null; then cat "$work/server.log" >&2; echo "climpact-web exited" >&2; exit 1; fi
  sleep 1
done
if [ -z "${body:-}" ]; then cat "$work/server.log" >&2; echo "no answer from /healthz" >&2; exit 1; fi
echo "$body"
"$bin/python" -I -c "import json, sys; assert json.loads(sys.argv[1])['database'] == 'ok'" "$body"
# A page that uses the static files: the stylesheet is collected and served.
css=$(curl -fsS "http://127.0.0.1:$port/" | grep -o 'href="[^"]*climpact[^"]*\.css"' | head -n1 | cut -d'"' -f2)
if [ -z "$css" ]; then echo "the home page links no climpact stylesheet" >&2; exit 1; fi
curl -fsS -o /dev/null "http://127.0.0.1:$port$css"
echo "stylesheet $css served"
echo "--- wheels $version OK"
