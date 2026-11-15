"""Check that an index serves exactly the files a release built, and download the wheels
(#131): release.yml runs it after the TestPyPI upload, then smoke-tests the downloads.

    python scripts/fetch_published.py https://test.pypi.org 0.1.0rc1 dist downloaded

For climpact and climpact-web at VERSION, waits (up to --timeout seconds; a new upload
can take a minute to appear) until the index's JSON API lists the version's wheel and
sdist, checks their SHA-256 against the files in DIST, and downloads the two wheels to OUT,
checking them again. Standard library only. Exits 1 on a mismatch or a timeout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PACKAGES = {"climpact": "climpact", "climpact-web": "climpact_web"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "climpact-release-check"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def listed(index: str, name: str, version: str) -> dict[str, dict] | None:
    """The version's files on the index, by file name, or None if not there yet."""
    try:
        data = json.loads(get(f"{index}/pypi/{name}/{version}/json"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
    return {f["filename"]: f for f in data.get("urls", [])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("index", help="index base URL, e.g. https://test.pypi.org")
    parser.add_argument("version")
    parser.add_argument("dist", type=Path, help="the files the release built")
    parser.add_argument("out", type=Path, help="folder for the downloaded wheels")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args(argv)
    index = args.index.rstrip("/")
    args.out.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + args.timeout

    for name, stem in PACKAGES.items():
        wanted = {
            f"{stem}-{args.version}-py3-none-any.whl",
            f"{stem}-{args.version}.tar.gz",
        }
        while True:
            files = listed(index, name, args.version) or {}
            if wanted <= files.keys():
                break
            if time.monotonic() > deadline:
                print(f"{index}: {name} {args.version} lists {sorted(files)}", file=sys.stderr)
                return 1
            print(f"waiting for {index} to list {name} {args.version} ...")
            time.sleep(15)
        for filename in sorted(wanted):
            local = sha256((args.dist / filename).read_bytes())
            remote = files[filename]["digests"]["sha256"]
            if local != remote:
                print(f"{filename}: index has {remote}, built {local}", file=sys.stderr)
                return 1
            print(f"{filename}: sha256 {local} matches")
            if filename.endswith(".whl"):
                data = get(files[filename]["url"])
                if sha256(data) != local:
                    print(f"{filename}: the download does not match", file=sys.stderr)
                    return 1
                (args.out / filename).write_bytes(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
