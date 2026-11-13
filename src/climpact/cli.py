"""Command-line interface: ``climpact run <station file> --out <dir>``.

Computes every ported output for one station and writes them as Climpact CSV files to
``<dir>/<station>/{indices,qc}/``, as the R app does.
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
    return parser


def _custom(args: argparse.Namespace, parser: argparse.ArgumentParser) -> CustomIndex | None:
    if args.no_custom:
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
    from climpact.io.output_files import write_outputs
    from climpact.outputs import build_all
    from climpact.station import load_station

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
    run = load_station(args.station_file, metadata, params)
    tables = build_all(run)
    written = write_outputs(tables, metadata, params, args.out)
    skipped = sorted(set(tables) - set(written))
    print(f"Wrote {len(written)} files to {args.out / metadata.name}")
    if skipped:
        print(f"Not written (no data in any period): {', '.join(skipped)}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return run_command(args, parser)
    parser.error(f"unknown command {args.command!r}")  # pragma: no cover
    return 2


if __name__ == "__main__":
    sys.exit(main())
