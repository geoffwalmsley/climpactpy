"""Download GHCN-Daily stations and convert them to Climpact's station input format.

    uv run python reference/fetch_ghcn.py              # every station in stations.csv
    uv run python reference/fetch_ghcn.py minneapolis  # selected runs only

Source: NOAA NCEI GHCN-Daily, one CSV per station (Menne et al. 2012, doi:10.7289/V5D21VHZ):
https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/<ID>.csv

Conversion rules (see reference/README.md):
  - one row per calendar day from 1 January of ``start`` to 31 December of ``end``;
  - tab-separated ``year month day prcp tmax tmin``;
  - GHCN values are tenths of mm / degC, so they are divided by 10;
  - a value whose QFLAG (second attribute) is not blank failed GHCN quality control and is
    written as missing;
  - missing is written as -99.9.

Rows of stations.csv whose ``source`` is not ``ghcn`` (lat0 and sydney, which use Climpact's own
sample file) are skipped.

Downloads are cached in reference/.ghcn-cache/ (gitignored). Use --refresh to download again.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATIONS_CSV = HERE / "stations.csv"
INPUT_DIR = HERE / "input"
CACHE_DIR = HERE / ".ghcn-cache"
URL = "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/{id}.csv"
ELEMENTS = ("PRCP", "TMAX", "TMIN")
MISSING = "-99.9"


def read_stations(path: Path = STATIONS_CSV) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def station_file(row: dict[str, str]) -> str:
    """File stem used for the input file and the R output folder."""
    return f"{row['name']}_{row['start']}-{row['end']}"


def download(station_id: str, refresh: bool = False) -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / f"{station_id}.csv"
    if refresh or not path.exists():
        tmp = path.with_suffix(".part")
        with urllib.request.urlopen(URL.format(id=station_id), timeout=120) as resp:
            tmp.write_bytes(resp.read())
        tmp.rename(path)
    return path


def _format(raw: str) -> str:
    """Tenths to units, without trailing zeros (as in Climpact's sample file)."""
    tenths = int(raw)
    if tenths == 0:
        return "0"
    return f"{tenths / 10:.1f}".removesuffix(".0")


def parse_value(value: str, attributes: str) -> str:
    """Convert one GHCN value; blank or QC-flagged values become missing."""
    value = value.strip()
    if not value:
        return MISSING
    flags = attributes.split(",")
    qflag = flags[1].strip() if len(flags) > 1 else ""
    if qflag:
        return MISSING
    return _format(value)


def convert(ghcn_csv: Path, start: int, end: int) -> tuple[list[str], dict[str, int]]:
    """Return the Climpact input lines and the number of QC-flagged values per element."""
    by_date: dict[str, tuple[str, str, str]] = {}
    flagged = dict.fromkeys(ELEMENTS, 0)
    with ghcn_csv.open(newline="") as f:
        for rec in csv.DictReader(f):
            date = rec["DATE"]
            if not (str(start) <= date[:4] <= str(end)):
                continue
            values = []
            for elem in ELEMENTS:
                raw = (rec.get(elem) or "").strip()
                attrs = rec.get(f"{elem}_ATTRIBUTES") or ""
                v = parse_value(raw, attrs)
                if raw and v == MISSING:
                    flagged[elem] += 1
                values.append(v)
            by_date[date] = tuple(values)

    lines = []
    day = dt.date(start, 1, 1)
    last = dt.date(end, 12, 31)
    while day <= last:
        prcp, tmax, tmin = by_date.get(day.isoformat(), (MISSING, MISSING, MISSING))
        lines.append(f"{day.year}\t{day.month}\t{day.day}\t{prcp}\t{tmax}\t{tmin}")
        day += dt.timedelta(days=1)
    return lines, flagged


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("runs", nargs="*", help="runs from stations.csv (default: all)")
    parser.add_argument("--refresh", action="store_true", help="download again")
    parser.add_argument("--out-dir", type=Path, default=INPUT_DIR)
    args = parser.parse_args(argv)

    rows = read_stations()
    known = {r["run"] for r in rows}
    unknown = set(args.runs) - known
    if unknown:
        parser.error(f"unknown run(s): {', '.join(sorted(unknown))}")

    done = set()
    for row in rows:
        if args.runs and row["run"] not in args.runs:
            continue
        if row["source"] != "ghcn":  # lat0/sydney use Climpact's own sample file
            print(f"{row['run']:12s} skipped: source is {row['source']}, not ghcn")
            continue
        stem = station_file(row)
        if stem in done:  # several runs can share one input file
            continue
        done.add(stem)
        src = download(row["id"], refresh=args.refresh)
        lines, flagged = convert(src, int(row["start"]), int(row["end"]))
        out = args.out_dir / f"{stem}.txt"
        out.write_text("\n".join(lines) + "\n")
        missing = [sum(1 for line in lines if line.split("\t")[i] == MISSING) for i in (3, 4, 5)]
        print(
            f"{row['run']:12s} {row['id']} -> {out.name}: {len(lines)} days, "
            f"missing prcp/tmax/tmin {missing[0]}/{missing[1]}/{missing[2]}, "
            f"QC-flagged {flagged['PRCP']}/{flagged['TMAX']}/{flagged['TMIN']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
