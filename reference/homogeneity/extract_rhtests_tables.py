"""Extract RHtestsV4's critical-value tables for the Python port (#34).

    uv run python reference/homogeneity/extract_rhtests_tables.py
    uv run python reference/homogeneity/extract_rhtests_tables.py --source RHtestsV4_20190301.r

RHtestsV4 embeds two tables in its R code, as ``itmp<-matrix(c(...),ncol=8,byrow=T)``:

- ``readPFtable``: empirical percentiles of the PFmax statistic of the penalised maximal F
  test (PMFred, ``PFmax31red_Nmin10``), for series lengths N from 20 to 1200;
- ``readPTtable``: empirical percentiles of the PTmax statistic of the penalised maximal t
  test (PMTred, ``PTmaxRed_Nmin5``), for N from 10 to 1200.

Each row is N, the 75th, 80th, 90th, 95th, 99th and 99.99th percentiles and the lag-1
autocorrelation they were simulated with (44 values from -0.2 to 0.975 per N). This script
reads them from ``RHtestsV4_20190301.r`` at the commit the R reference image uses
(downloaded, or ``--source``; its SHA-256 is checked) and writes them, as written in the R
source, to ``packages/climpact/src/climpact/homogeneity/data/``, where
:mod:`climpact.homogeneity.rhtests` reads them.

RHtests is © Environment and Climate Change Canada (Xiaolan L. Wang and Yang Feng),
distributed under the GNU Lesser General Public License 2.1
(https://github.com/ECCC-CDAS/RHtests); the tables are part of it.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import urllib.request
from pathlib import Path

COMMIT = "827b2b2254da41f3a3c57cb61390d9f57a22e07f"
URL = f"https://raw.githubusercontent.com/ECCC-CDAS/RHtests/{COMMIT}/V4_files/RHtestsV4_20190301.r"
SHA256 = "a2ff2e03f20499230500cb84abdcbaa19855459ffe08ec5e573ccb81bd1ebf13"

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "packages" / "climpact" / "src" / "climpact" / "homogeneity" / "data"
HEADER = ["n", "p75", "p80", "p90", "p95", "p99", "p9999", "phi"]
# R function holding the table -> output file
TABLES = {"readPFtable": "pfmax31red_nmin10.csv", "readPTtable": "ptmaxred_nmin5.csv"}


def source_text(path: Path | None) -> str:
    data = path.read_bytes() if path else urllib.request.urlopen(URL, timeout=60).read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SHA256:
        raise SystemExit(f"RHtestsV4_20190301.r has SHA-256 {digest}, expected {SHA256}")
    return data.decode("latin-1")


def table(text: str, function: str) -> list[list[str]]:
    """The rows of the ``itmp<-matrix(c(...),ncol=8,byrow=T)`` table in ``function``."""
    start = text.index(f"\n{function}<-function(")
    body = text[start : text.index("),ncol=8,byrow=T)", start)]
    body = body[body.index("itmp<-matrix(c(") + len("itmp<-matrix(c(") :]
    lines = [re.sub(r"#.*", "", line) for line in body.splitlines()]
    values = [v.strip() for v in ",".join(lines).split(",") if v.strip()]
    if len(values) % len(HEADER):
        raise SystemExit(f"{function}: {len(values)} values is not a whole number of rows")
    rows = [values[i : i + len(HEADER)] for i in range(0, len(values), len(HEADER))]
    for row in rows:
        [float(v) for v in row]  # every value is a number
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", type=Path, help="a local copy of RHtestsV4_20190301.r")
    args = parser.parse_args()
    text = source_text(args.source)
    OUT.mkdir(parents=True, exist_ok=True)
    for function, name in TABLES.items():
        rows = table(text, function)
        with open(OUT / name, "w", newline="") as f:
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(HEADER)
            writer.writerows(rows)
        print(f"{name}: {len(rows)} rows")


if __name__ == "__main__":
    main()
