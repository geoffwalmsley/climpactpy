"""Command-line interface.

``climpact run <station file> --out <dir>`` computes every ported output for one station
and writes them as Climpact CSV files to ``<dir>/<station>/{indices,qc,thres}/``, as the R
app does. ``climpact batch <metadata file> <data dir> --out <dir>`` does the same for every
station of an R batch metadata file (see :mod:`climpact.batch`).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from climpact import __version__
from climpact.config import CustomIndex, IndexParams, StationMetadata

DEFAULTS = IndexParams()
_DEFAULT = "default: %(default)s"
CUSTOM = CustomIndex()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="climpact", description="Climpact indices of daily climate extremes."
    )
    parser.add_argument("--version", action="version", version=f"climpactpy {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser(
        "run",
        help="calculate the indices for a station and write Climpact CSV files",
        description="Calculate the indices for one station and write them as Climpact "
        "CSV files to OUT/NAME/{indices,qc}/. Defaults are the Climpact app defaults.",
    )
    run.add_argument("station_file", type=Path, help="Climpact/RClimDex station text file")
    run.add_argument("--out", type=Path, required=True, help="output folder")

    station = run.add_argument_group("station")
    station.add_argument("--name", help="station name (default: the file name without suffix)")
    station.add_argument("--lat", type=float, default=0.0, help="latitude (default: %(default)s)")
    station.add_argument("--lon", type=float, default=0.0, help="longitude (default: %(default)s)")
    station.add_argument(
        "--base-start", type=int, default=1971, help="first base period year (default: %(default)s)"
    )
    station.add_argument(
        "--base-end", type=int, default=2000, help="last base period year (default: %(default)s)"
    )

    params = run.add_argument_group("index parameters")
    params.add_argument("--wsdi-days", type=int, default=DEFAULTS.wsdi_days, help=_DEFAULT)
    params.add_argument("--csdi-days", type=int, default=DEFAULTS.csdi_days, help=_DEFAULT)
    params.add_argument("--rx-days", type=int, default=DEFAULTS.rx_days, help=_DEFAULT)
    params.add_argument("--txtn-days", type=int, default=DEFAULTS.txtn_days, help=_DEFAULT)
    params.add_argument("--hdd-base", type=float, default=DEFAULTS.hdd_base, help=_DEFAULT)
    params.add_argument("--cdd-base", type=float, default=DEFAULTS.cdd_base, help=_DEFAULT)
    params.add_argument("--gdd-base", type=float, default=DEFAULTS.gdd_base, help=_DEFAULT)
    params.add_argument("--rnnmm", type=float, default=DEFAULTS.rnnmm, help=_DEFAULT)
    params.add_argument("--spei-months", type=int, default=DEFAULTS.spei_months, help=_DEFAULT)
    custom = params.add_mutually_exclusive_group()
    custom.add_argument(
        "--custom",
        nargs=3,
        metavar=("VAR", "OP", "VALUE"),
        default=[CUSTOM.variable, CUSTOM.operator, str(CUSTOM.threshold)],
        help="custom index: VAR is TX, TN, TM, PR or DTR; OP is >, >=, < or <= (default: TN > 0)",
    )
    custom.add_argument("--no-custom", action="store_true", help="skip the custom index")

    batch = commands.add_parser(
        "batch",
        help="calculate the indices for every station of an R batch metadata file",
        description="Calculate the indices for every station listed in a Climpact R batch "
        "metadata file and write each to OUT/NAME/, as `climpact run` does. NAME is the "
        "station file name without its extension. Index parameters come from the metadata "
        "file. A station that fails is reported in OUT/NAME.errors.txt and the batch "
        "carries on.",
    )
    batch.add_argument(
        "metadata_file",
        type=Path,
        help="R batch metadata file: a header row, then station_file latitude longitude "
        "wsdin csdin Tb_HDD Tb_CDD Tb_GDD rxnday rnnmm txtn SPEI per station",
    )
    batch.add_argument("data_dir", type=Path, help="folder holding the station files")
    batch.add_argument("--out", type=Path, required=True, help="output folder")
    batch.add_argument(
        "--base-start", type=int, default=1971, help="first base period year (default: %(default)s)"
    )
    batch.add_argument(
        "--base-end", type=int, default=2000, help="last base period year (default: %(default)s)"
    )
    batch.add_argument(
        "--workers",
        type=int,
        default=None,
        help="number of stations to run at once (default: one per CPU)",
    )
    batch.add_argument(
        "--custom",
        nargs=3,
        metavar=("VAR", "OP", "VALUE"),
        default=None,
        help="custom index for every station: VAR is TX, TN, TM, PR or DTR; OP is >, >=, < "
        "or <= (default: none, as in R's batch mode)",
    )
    return parser


def _custom(args: argparse.Namespace, parser: argparse.ArgumentParser) -> CustomIndex | None:
    if getattr(args, "no_custom", False) or args.custom is None:
        return None
    variable, op, value = args.custom
    if variable not in ("TX", "TN", "TM", "PR", "DTR"):
        parser.error(f"--custom: unknown variable {variable!r}")
    if op not in (">", ">=", "<", "<="):
        parser.error(f"--custom: unknown operator {op!r}")
    try:
        threshold = float(value)
    except ValueError:
        parser.error(f"--custom: threshold {value!r} is not a number")
    return CustomIndex(variable=variable, operator=op, threshold=threshold)


def run_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from climpact.batch import run_station

    if not args.station_file.is_file():
        parser.error(f"station file not found: {args.station_file}")
    metadata = StationMetadata(
        name=args.name or args.station_file.stem,
        latitude=args.lat,
        longitude=args.lon,
        base_start=args.base_start,
        base_end=args.base_end,
    )
    params = IndexParams(
        wsdi_days=args.wsdi_days,
        csdi_days=args.csdi_days,
        rx_days=args.rx_days,
        txtn_days=args.txtn_days,
        hdd_base=args.hdd_base,
        cdd_base=args.cdd_base,
        gdd_base=args.gdd_base,
        rnnmm=args.rnnmm,
        spei_months=args.spei_months,
        custom=_custom(args, parser),
    )
    written, skipped = run_station(args.station_file, metadata, params, args.out)
    print(f"Wrote {len(written)} files to {args.out / metadata.name}")
    if skipped:
        print(f"Not written (no data in any period): {', '.join(skipped)}")
    return 0


def batch_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from climpact.batch import BatchMetadataError, StationResult, read_batch_metadata, run_batch

    if not args.metadata_file.is_file():
        parser.error(f"metadata file not found: {args.metadata_file}")
    if not args.data_dir.is_dir():
        parser.error(f"data folder not found: {args.data_dir}")
    if args.workers is not None and args.workers < 1:
        parser.error("--workers must be at least 1")
    custom = _custom(args, parser)
    try:
        stations = read_batch_metadata(args.metadata_file)
    except BatchMetadataError as exc:
        parser.error(str(exc))
    total = len(stations)
    print(f"Processing {total} stations to {args.out}")
    done = 0

    def report(result: StationResult) -> None:
        nonlocal done
        done += 1
        if result.ok:
            print(f"[{done}/{total}] {result.name}: wrote {result.written} files")
        else:
            first_line = result.error.splitlines()[0]
            print(f"[{done}/{total}] {result.name}: FAILED: {first_line}")

    results = run_batch(
        stations,
        args.data_dir,
        args.out,
        base_start=args.base_start,
        base_end=args.base_end,
        custom=custom,
        workers=args.workers,
        on_result=report,
    )
    failed = [r for r in results if not r.ok]
    print(f"Done: {total - len(failed)} of {total} stations processed, {len(failed)} failed")
    for result in failed:
        print(f"  {result.name}: see {result.error_file}")
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return run_command(args, parser)
    if args.command == "batch":
        return batch_command(args, parser)
    parser.error(f"unknown command {args.command!r}")  # pragma: no cover
    return 2


if __name__ == "__main__":
    sys.exit(main())
