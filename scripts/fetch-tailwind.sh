#!/bin/sh
# Download the standalone Tailwind CSS CLI into bin/tailwindcss (#118).
#
# One pinned release from the official tailwindlabs/tailwindcss GitHub release, for this
# platform, installed only if its SHA-256 matches the hash pinned below (from the release's
# sha256sums.txt; Tailwind publishes no artifact attestations, so the pin is the integrity
# control). No npm, nothing global. Upgrade only in a deliberate pull request that changes
# VERSION and every hash together.
#
#   scripts/fetch-tailwind.sh          # installs bin/tailwindcss (a no-op if it is current)
#   TAILWIND_BIN=path scripts/fetch-tailwind.sh
set -eu

VERSION=v4.3.3

case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) asset=tailwindcss-macos-arm64 ;;
    Darwin-x86_64) asset=tailwindcss-macos-x64 ;;
    Linux-x86_64) asset=tailwindcss-linux-x64 ;;
    Linux-aarch64 | Linux-arm64) asset=tailwindcss-linux-arm64 ;;
    *)
        echo "fetch-tailwind: no pinned Tailwind CLI for $(uname -s) $(uname -m)" >&2
        exit 1
        ;;
esac

case "$asset" in
    tailwindcss-macos-arm64) expected=cdf646702987a743464dff4d9c60fd4480d1c1e73dd819a9a67f1078815dce9d ;;
    tailwindcss-macos-x64) expected=7922e0953f2110c05976e3bf58f14e643d90427575e766b7d433f5f80cbee7e1 ;;
    tailwindcss-linux-x64) expected=dc61b3ac6b8c9ca874c0cc4c57b2409791a64c5540404ca5f5367360babc313a ;;
    tailwindcss-linux-arm64) expected=55fd0b241214eff3de1e8ee4f22796662f2d2e7a49bcfca7477cfd0bac398195 ;;
esac

root=$(cd "$(dirname "$0")/.." && pwd)
target=${TAILWIND_BIN:-$root/bin/tailwindcss}

sha256() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | cut -d' ' -f1
    else
        shasum -a 256 "$1" | cut -d' ' -f1
    fi
}

if [ -f "$target" ] && [ "$(sha256 "$target")" = "$expected" ]; then
    echo "fetch-tailwind: $target is Tailwind CSS $VERSION ($asset), checksum OK"
    exit 0
fi

url="https://github.com/tailwindlabs/tailwindcss/releases/download/$VERSION/$asset"
tmp=$(mktemp "${TMPDIR:-/tmp}/tailwindcss.XXXXXX")
trap 'rm -f "$tmp"' EXIT

echo "fetch-tailwind: downloading $url"
curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 -o "$tmp" "$url"

actual=$(sha256 "$tmp")
if [ "$actual" != "$expected" ]; then
    echo "fetch-tailwind: checksum mismatch for $asset $VERSION" >&2
    echo "  expected $expected" >&2
    echo "  got      $actual" >&2
    echo "Nothing was installed." >&2
    exit 1
fi

mkdir -p "$(dirname "$target")"
chmod 755 "$tmp"
mv "$tmp" "$target"
trap - EXIT
echo "fetch-tailwind: installed Tailwind CSS $VERSION ($asset) at $target, checksum OK"
