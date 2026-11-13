"""Command-line interface.

``climpact run <station file> --out <dir>`` computes every ported output for one station
and writes them as Climpact CSV files to ``<dir>/<station>/{indices,qc,thres}/``, as the R
app does. ``climpact batch <metadata file> <data dir> --out <dir>`` does the same for every
station of an R batch metadata file (see :mod:`climpact.batch`). Both take ``--qc``,
``--homogeneity`` and ``--indices`` to select the modules a run uses, and
``climpact modules`` lists the modules available (see :mod:`climpact.modules`). Both
take ``--plots`` to draw R's index plots and combined PDF and ``--zip`` to zip the
outputs, as R's download does (see :mod:`climpact.plots`).
``climpact gridded-thresholds <netCDF files> --out <file>`` computes the base-period
thresholds of every cell of a grid, as Climpact's ``climpact.ncdf.thresholds.wrapper.r``
(see :mod:`climpact.gridded`).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from climpact import __version__
from climpact.config import CustomIndex, IndexParams, StationMetadata
from climpact.modules import (
    DEFAULT_HOMOGENEITY,
    DEFAULT_INDICES,
    DEFAULT_QC,
    KINDS,
    ModuleSelection,
    UnknownModuleError,
)

DEFAULTS = IndexParams()
_DEFAULT = "default: %(default)s"
CUSTOM = CustomIndex()
_PROGRESS_HELP = "print each stage to standard error as it finishes"


def _print_stage(prefix: str, stage: str, step: int, total: int) -> None:
    print(f"{prefix}[{step}/{total}] {stage}", file=sys.stderr, flush=True)


def _module_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group(
        "modules", "Select the modules a run uses; `climpact modules` lists them."
    )
    group.add_argument(
        "--qc",
        default=",".join(DEFAULT_QC),
        metavar="NAMES",
        help="comma-separated QC modules, run in order (default: %(default)s)",
    )
    group.add_argument(
        "--homogeneity",
        default=DEFAULT_HOMOGENEITY,
        metavar="NAME",
        help="homogeneity module; its adjusted data, if any, is used for the indices "
        "(default: %(default)s)",
    )
    group.add_argument(
        "--indices",
        default=",".join(DEFAULT_INDICES),
        metavar="NAMES",
        help="comma-separated index modules, run in order (default: %(default)s)",
    )


def _output_arguments(parser: argparse.ArgumentParser, zip_help: str) -> None:
    group = parser.add_argument_group("plots and archive")
    group.add_argument(
        "--plots",
        action="store_true",
        help="also draw a PNG of every index and the combined PDF in NAME/plots/, as R "
        "does (needs matplotlib: pip install climpactpy[plots])",
    )
    group.add_argument("--zip", action="store_true", help=zip_help)


def _plots_available(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.plots:
        from climpact.plots import require_matplotlib

        try:
            require_matplotlib()
        except ImportError as exc:
            parser.error(f"--plots: {exc}")


def _names(text: str) -> tuple[str, ...]:
    return tuple(name.strip() for name in text.split(",") if name.strip())


def _modules(args: argparse.Namespace, parser: argparse.ArgumentParser) -> ModuleSelection:
    """The selected modules, checked to be available."""
    from climpact.modules import resolve

    selection = ModuleSelection(
        qc=_names(args.qc), homogeneity=args.homogeneity, indices=_names(args.indices)
    )
    try:
        resolve(selection)
    except (UnknownModuleError, TypeError) as exc:
        parser.error(str(exc))
    return selection


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
    _module_arguments(run)
    _output_arguments(run, "also zip the station folder to OUT/NAME.zip, as R's download")
    run.add_argument("--progress", action="store_true", help=_PROGRESS_HELP)

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
    _module_arguments(batch)
    _output_arguments(batch, "also zip the whole output folder to OUT.zip next to it, as R does")
    batch.add_argument("--progress", action="store_true", help=_PROGRESS_HELP)

    grid = commands.add_parser(
        "gridded-thresholds",
        help="calculate the base-period thresholds of every cell of a netCDF grid",
        description="Calculate the base-period percentile thresholds of every cell of a "
        "grid of daily TX, TN and precipitation, and write them to a netCDF file in the "
        "layout of Climpact's climpact.ncdf.thresholds.wrapper.r. Temperatures may be in "
        "K or degrees_C, precipitation in kg m-2 d-1 or kg m-2 s-1.",
    )
    grid.add_argument("input_files", type=Path, nargs="+", help="one to three CF netCDF files")
    grid.add_argument("--out", type=Path, required=True, help="thresholds netCDF file to write")
    grid.add_argument("--tmax", default="tasmax", help="TX variable name (" + _DEFAULT + ")")
    grid.add_argument("--tmin", default="tasmin", help="TN variable name (" + _DEFAULT + ")")
    grid.add_argument("--prec", default="pr", help="precipitation variable name (" + _DEFAULT + ")")
    grid.add_argument(
        "--base-start", type=int, default=1971, help="first base period year (default: %(default)s)"
    )
    grid.add_argument(
        "--base-end", type=int, default=2000, help="last base period year (default: %(default)s)"
    )
    grid.add_argument("--institution", default=None, help="author institution (global attribute)")
    grid.add_argument("--institution-id", default=None, help="author institution id")
    grid.add_argument(
        "--workers", type=int, default=1, help="threads computing cells (" + _DEFAULT + ")"
    )
    grid.add_argument(
        "--max-values",
        type=float,
        default=5.0,
        metavar="MILLIONS",
        help="millions of input values read at once, which bounds memory "
        "(R's max.vals.millions; " + _DEFAULT + ")",
    )
    grid.add_argument("--quiet", action="store_true", help="do not print progress")

    commands.add_parser(
        "modules",
        help="list the QC, homogeneity and index modules available",
        description="List the built-in modules and the plugins installed through the "
        "climpact.qc, climpact.homogeneity and climpact.indices entry points.",
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
    modules = _modules(args, parser)
    _plots_available(args, parser)
    progress = None
    if args.progress:

        def progress(stage: str, step: int, total: int) -> None:
            _print_stage("", stage, step, total)

    written, skipped = run_station(
        args.station_file,
        metadata,
        params,
        args.out,
        modules=modules,
        progress=progress,
        plots=args.plots,
        zip=args.zip,
    )
    archive = written.pop("zip", None)
    print(f"Wrote {len(written)} files to {args.out / metadata.name}")
    if archive is not None:
        print(f"Zipped them to {archive}")
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
    modules = _modules(args, parser)
    _plots_available(args, parser)
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

    progress = None
    if args.progress:

        def progress(station: str, stage: str, step: int, steps: int) -> None:
            _print_stage(f"{station} ", stage, step, steps)

    results = run_batch(
        stations,
        args.data_dir,
        args.out,
        base_start=args.base_start,
        base_end=args.base_end,
        custom=custom,
        workers=args.workers,
        on_result=report,
        modules=modules,
        progress=progress,
        plots=args.plots,
        zip=args.zip,
    )
    failed = [r for r in results if not r.ok]
    print(f"Done: {total - len(failed)} of {total} stations processed, {len(failed)} failed")
    if args.zip:
        print(f"Zipped the output folder to {args.out.parent / (args.out.name + '.zip')}")
    for result in failed:
        print(f"  {result.name}: see {result.error_file}")
    return 1 if failed else 0


def gridded_thresholds_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from climpact.gridded import open_grid, write_grid_thresholds
    from climpact.thresholds import InsufficientBaseData

    for path in args.input_files:
        if not path.is_file():
            parser.error(f"input file not found: {path}")
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if args.base_end < args.base_start:
        parser.error("--base-end is before --base-start")
    names = {"tasmax": args.tmax, "tasmin": args.tmin, "pr": args.prec}
    try:
        inp = open_grid(args.input_files, names, max_values=int(args.max_values * 1e6))
    except (ValueError, NotImplementedError) as exc:
        parser.error(str(exc))
    author = {"institution": args.institution, "institution_id": args.institution_id}
    ny, nx = inp.shape

    def progress(stage: str, done: int, total: int) -> None:
        if not args.quiet:
            print(f"[{done}/{total}] blocks done", flush=True)

    if not args.quiet:
        print(
            f"{ny} x {nx} cells, {inp.time[0]:%Y-%m-%d} to {inp.time[-1]:%Y-%m-%d}, "
            f"base period {args.base_start}-{args.base_end}"
        )
    try:
        write_grid_thresholds(
            inp, args.out, args.base_start, args.base_end, author, args.workers, progress
        )
    except InsufficientBaseData as exc:
        parser.error(str(exc))
    print(f"Wrote {args.out}")
    return 0


def modules_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from climpact.modules import available

    for kind in KINDS:
        print(f"{kind}:")
        for name, source in available(kind).items():
            print(f"  {name} ({source})")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return run_command(args, parser)
    if args.command == "batch":
        return batch_command(args, parser)
    if args.command == "modules":
        return modules_command(args, parser)
    if args.command == "gridded-thresholds":
        return gridded_thresholds_command(args, parser)
    parser.error(f"unknown command {args.command!r}")  # pragma: no cover
    return 2


if __name__ == "__main__":
    sys.exit(main())
