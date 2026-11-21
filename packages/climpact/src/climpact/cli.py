"""Command-line interface.

``climpact run <station file> --out <dir>`` computes every ported output for one station
and writes them as Climpact CSV files to ``<dir>/<station>/{indices,qc,thres}/``, as the R
app does. ``climpact batch <metadata file> <data dir> --out <dir>`` does the same for every
station of an R batch metadata file (see :mod:`climpact.batch`). Both take ``--qc``,
``--homogeneity`` and ``--indices`` to select the modules a run uses, and
``--module-option`` and ``--module-options`` to set their options; ``climpact modules``
lists the modules available and their options (see :mod:`climpact.modules`). Both
take ``--plots`` to draw R's index plots and combined PDF and ``--zip`` to zip the
outputs, as R's download does (see :mod:`climpact.plots`), and ``--report`` to write a PDF
report of each station (see :mod:`climpact.report`).
``climpact gridded-thresholds <netCDF files> --out <file>`` computes the base-period
thresholds of every cell of a grid, as Climpact's ``climpact.ncdf.thresholds.wrapper.r``
(see :mod:`climpact.gridded`). The gridded commands take the files of a variable split
along time (one per year, say) as several files or a pattern such as ``'tasmax_*.nc'``.
``climpact gridded-indices <netCDF files> --out <dir>`` computes the indices of every
cell, as ``climpact.ncdf.wrapper.r``; with ``--trends`` it also writes ``trends.nc``, the
trends of every cell (:mod:`climpact.gridded.trends`).
``climpact sector-correlation <station file> <sector file> --out <dir>`` correlates annual
sector data with a station already run, as the app's step 4 (see :mod:`climpact.sector`).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from climpact.config import CustomIndex, IndexParams, StationMetadata
from climpact.io.output_files import software_credit
from climpact.modules import (
    DEFAULT_HOMOGENEITY,
    DEFAULT_INDICES,
    DEFAULT_QC,
    KINDS,
    ModuleOptionError,
    ModuleSelection,
    UnknownModuleError,
)

DEFAULTS = IndexParams()
_DEFAULT = "default: %(default)s"
CUSTOM = CustomIndex()
_PROGRESS_HELP = "print each stage to standard error as it finishes"


def _add_grid_input_args(parser: argparse.ArgumentParser) -> None:
    """The options of the gridded commands for reading the input in blocks."""
    parser.add_argument(
        "--max-values",
        type=float,
        default=5.0,
        metavar="MILLIONS",
        help="millions of input values read at once, which bounds memory "
        "(R's max.vals.millions; " + _DEFAULT + ")",
    )
    parser.add_argument(
        "--rechunk",
        choices=("auto", "yes", "no"),
        default="auto",
        help="copy the input to a temporary file chunked by block before reading it; auto "
        "does so for files chunked by time step over the grid, which every block would "
        "otherwise read in full (" + _DEFAULT + ")",
    )
    parser.add_argument(
        "--tmp-dir",
        type=Path,
        default=None,
        help="directory for the rechunked copy, about the size of the uncompressed input "
        "(default: the system's temporary directory)",
    )
    parser.add_argument("--quiet", action="store_true", help="do not print progress")


_INPUT_FILES_HELP = (
    "CF netCDF files, or patterns such as 'tasmax_day_*.nc' (quoted, or expanded by the "
    "shell); a variable may be split along time across several files, joined in the "
    "order of their first day"
)


def _input_files(args: argparse.Namespace, parser: argparse.ArgumentParser) -> list[Path]:
    """The input files, with any pattern (``*``, ``?``, ``[...]``) that is not itself a
    file expanded to the files it matches, in name order."""
    import glob

    out: list[Path] = []
    for path in args.input_files:
        if not path.is_file() and glob.has_magic(str(path)):
            matches = sorted(Path(m) for m in glob.glob(str(path)) if Path(m).is_file())
            if not matches:
                parser.error(f"no file matches {path}")
            out.extend(matches)
        elif not path.is_file():
            parser.error(f"input file not found: {path}")
        else:
            out.append(path)
    return list(dict.fromkeys(out))


def _open_grid_args(args: argparse.Namespace) -> dict:
    return {
        "names": {"tasmax": args.tmax, "tasmin": args.tmin, "pr": args.prec},
        "max_values": int(args.max_values * 1e6),
        "rechunk": {"auto": None, "yes": True, "no": False}[args.rechunk],
        "tmp_dir": args.tmp_dir,
    }


def _grid_progress(args: argparse.Namespace):
    def progress(stage: str, done: int, total: int) -> None:
        if not args.quiet:
            what = "time slabs rechunked" if stage == "rechunk" else "blocks done"
            print(f"[{done}/{total}] {what}", flush=True)

    return progress


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
    group.add_argument(
        "--module-option",
        action="append",
        default=[],
        metavar="[KIND:]NAME.OPTION=VALUE",
        help="set an option of a selected module, e.g. example_shift.adjustment=2; "
        "KIND (qc, homogeneity or indices) is needed only when modules of two kinds share "
        "NAME. Repeat for several options",
    )
    group.add_argument(
        "--module-options",
        type=Path,
        metavar="FILE",
        help="TOML file of module options, one table per module: [KIND.NAME] then "
        "OPTION = VALUE lines; --module-option overrides it",
    )


def _output_arguments(parser: argparse.ArgumentParser, zip_help: str, report_help: str) -> None:
    group = parser.add_argument_group("plots and archive")
    group.add_argument(
        "--plots",
        action="store_true",
        help="also draw a PNG of every index and the combined PDF in NAME/plots/, as R "
        "does (needs matplotlib: pip install 'climpact[plots]')",
    )
    group.add_argument("--zip", action="store_true", help=zip_help)
    group.add_argument("--report", action="store_true", help=report_help)


def _plots_available(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    flags = [f for f in ("plots", "report") if getattr(args, f, False)]
    if flags:
        from climpact.plots import require_matplotlib

        try:
            require_matplotlib()
        except ImportError as exc:
            parser.error(f"--{flags[0]}: {exc}")


def _names(text: str) -> tuple[str, ...]:
    return tuple(name.strip() for name in text.split(",") if name.strip())


def _options_file(path: Path) -> dict[str, dict[str, dict]]:
    """The module options of a TOML file: ``[KIND.NAME]`` tables of ``OPTION = VALUE``."""
    import tomllib

    try:
        data = tomllib.loads(path.read_text())
    except OSError as exc:
        raise ModuleOptionError(f"cannot read {path}: {exc.strerror}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ModuleOptionError(f"{path}: {exc}") from None
    options: dict[str, dict[str, dict]] = {}
    for kind, by_module in data.items():
        if not isinstance(by_module, dict) or not all(
            isinstance(v, dict) for v in by_module.values()
        ):
            raise ModuleOptionError(f"{path}: expected [{kind}.NAME] tables of options")
        options[kind] = {name: dict(values) for name, values in by_module.items()}
    return options


def _parse_module_option(text: str, selection: ModuleSelection) -> tuple[str, str, str, str]:
    """``(kind, module, option, value)`` of a ``[KIND:]NAME.OPTION=VALUE`` argument."""
    target, sep, value = text.partition("=")
    module, dot, option = target.strip().rpartition(".")
    if not (sep and dot and module and option):
        raise ModuleOptionError(f"--module-option {text!r}: expected [KIND:]NAME.OPTION=VALUE")
    kind, colon, name = module.partition(":")
    if colon:
        if kind not in KINDS:
            raise ModuleOptionError(
                f"--module-option {text!r}: unknown kind {kind!r} (kinds: {', '.join(KINDS)})"
            )
        return kind, name, option, value.strip()
    kinds = [k for k in KINDS if module in selection.names(k)]
    if not kinds:
        raise ModuleOptionError(f"--module-option {text!r}: no module {module!r} is selected")
    if len(kinds) > 1:
        raise ModuleOptionError(
            f"--module-option {text!r}: {module!r} is a selected {' and '.join(kinds)} module; "
            f"write {kinds[0]}:{module}.{option}=..."
        )
    return kinds[0], module, option, value.strip()


def _modules(args: argparse.Namespace, parser: argparse.ArgumentParser) -> ModuleSelection:
    """The selected modules and their options, checked to be available and valid."""
    from climpact.modules import resolve

    selection = ModuleSelection(
        qc=_names(args.qc), homogeneity=args.homogeneity, indices=_names(args.indices)
    )
    try:
        options = _options_file(args.module_options) if args.module_options else {}
        for text in args.module_option:
            kind, name, option, value = _parse_module_option(text, selection)
            options.setdefault(kind, {}).setdefault(name, {})[option] = value
        selection = ModuleSelection(selection.qc, selection.homogeneity, selection.indices, options)
        resolve(selection)
    except (UnknownModuleError, ModuleOptionError, TypeError) as exc:
        parser.error(str(exc))
    return selection


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="climpact", description="Climpact indices of daily climate extremes."
    )
    parser.add_argument("--version", action="version", version=software_credit())
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
    _output_arguments(
        run,
        "also zip the station folder to OUT/NAME.zip, as R's download",
        "also write a PDF report (cover with the settings, quality-control summary, a page "
        "per index with its plot and trends) to OUT/NAME_report.pdf (needs matplotlib)",
    )
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
    _output_arguments(
        batch,
        "also zip the whole output folder to OUT.zip next to it, as R does",
        "also write each station's PDF report to OUT_reports/NAME_report.pdf next to OUT "
        "(needs matplotlib)",
    )
    batch.add_argument("--progress", action="store_true", help=_PROGRESS_HELP)

    grid = commands.add_parser(
        "gridded-thresholds",
        help="calculate the base-period thresholds of every cell of a netCDF grid",
        description="Calculate the base-period percentile thresholds of every cell of a "
        "grid of daily TX, TN and precipitation, and write them to a netCDF file in the "
        "layout of Climpact's climpact.ncdf.thresholds.wrapper.r. Temperatures may be in "
        "K or degrees_C, precipitation in kg m-2 d-1 or kg m-2 s-1.",
    )
    grid.add_argument("input_files", type=Path, nargs="+", help=_INPUT_FILES_HELP)
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
    _add_grid_input_args(grid)

    gi = commands.add_parser(
        "gridded-indices",
        help="calculate the indices of every cell of a netCDF grid",
        description="Calculate the indices of every cell of a grid of daily TX, TN and "
        "precipitation, and write one netCDF file per index and frequency in the layout "
        "of Climpact's climpact.ncdf.wrapper.r. Temperatures may be in K or degrees_C, "
        "precipitation in kg m-2 d-1 or kg m-2 s-1. Not yet written: hw, hwEHF, spi, spei.",
    )
    gi.add_argument("input_files", type=Path, nargs="+", help=_INPUT_FILES_HELP)
    gi.add_argument("--out", type=Path, required=True, help="output directory")
    gi.add_argument(
        "--template",
        default=None,
        help="output file name template in CMIP5 form, var_freq_model_emissions_run_"
        "start-end.nc (R's file.template; default: var_daily_climpact_historical_NA_"
        "<first year>-<last year>.nc)",
    )
    gi.add_argument("--tmax", default="tasmax", help="TX variable name (" + _DEFAULT + ")")
    gi.add_argument("--tmin", default="tasmin", help="TN variable name (" + _DEFAULT + ")")
    gi.add_argument("--prec", default="pr", help="precipitation variable name (" + _DEFAULT + ")")
    gi.add_argument(
        "--base-start", type=int, default=1971, help="first base period year (default: %(default)s)"
    )
    gi.add_argument(
        "--base-end", type=int, default=2000, help="last base period year (default: %(default)s)"
    )
    gi.add_argument(
        "--indices",
        nargs="+",
        default=None,
        metavar="INDEX",
        help="indices to calculate, by short name (fd, rxdday, wsdid, ...; R's indices); "
        "default: all",
    )
    gi.add_argument(
        "--thresholds",
        type=Path,
        default=None,
        help="thresholds file from 'climpact gridded-thresholds' (R's thresholds.files); "
        "only for data with no day in the base period",
    )
    gi.add_argument("--institution", default=None, help="author institution (global attribute)")
    gi.add_argument("--institution-id", default=None, help="author institution id")
    from climpact.gridded.indices import WRAPPER_PARAMS as W

    for flag, attr, kind, text in (
        ("--wsdi-days", "wsdi_days", int, "days for wsdi<n> (R's wsdin_n)"),
        ("--csdi-days", "csdi_days", int, "days for csdi<n> (R's csdin_n)"),
        ("--rx-days", "rx_days", int, "days for rx<n>day (R's rxnday_n)"),
        ("--txtn-days", "txtn_days", int, "days for tx<n>tn<n>, txb<n>tnb<n> (ntxntn_n)"),
        ("--hdd-base", "hdd_base", float, "base temperature of hddheat (hddheatn_n)"),
        ("--cdd-base", "cdd_base", float, "base temperature of cddcold (cddcoldn_n)"),
        ("--gdd-base", "gdd_base", float, "base temperature of gddgrow (gddgrown_n)"),
        ("--rnnmm", "rnnmm", float, "precipitation threshold of r<nn>mm (rnnmm_n)"),
    ):
        gi.add_argument(
            flag, dest=attr, type=kind, default=getattr(W, attr), help=f"{text}; {_DEFAULT}"
        )
    gi.add_argument(
        "--trends",
        action="store_true",
        help="also write trends.nc: each cell's Sen's slope per decade with its 95%% interval "
        "and base-period mean, and the grid mean, of every annual index and of each "
        "calendar month of every monthly index (R has no counterpart)",
    )
    gi.add_argument(
        "--workers", type=int, default=1, help="threads computing cells (" + _DEFAULT + ")"
    )
    _add_grid_input_args(gi)

    sector = commands.add_parser(
        "sector-correlation",
        help="correlate annual sector data with a station's temperatures and indices",
        description="Correlate annual sector data (for example crop yields) with the "
        "yearly temperatures and indices of a station already run with `climpact run`, as "
        "step 4 of the Climpact app, and write R's correlation files to OUT/NAME/corr/. "
        "The indices are read from OUT/NAME/indices/.",
    )
    sector.add_argument("station_file", type=Path, help="the station's input text file")
    sector.add_argument(
        "sector_file", type=Path, help="CSV file with a header row, then Year,value per year"
    )
    sector.add_argument("--out", type=Path, required=True, help="output folder of the run")
    sector.add_argument("--name", help="station name (default: the file name without suffix)")
    sector.add_argument(
        "--no-detrend",
        action="store_true",
        help="correlate the sector data as given (default: detrended, as the app)",
    )
    sector.add_argument("--title", help="plot title (default: the station name)")
    sector.add_argument(
        "--y-label",
        help="y-axis label of the scatter plots (default: the sector file name up to its "
        "first '_' or '.')",
    )
    sector_out = sector.add_argument_group("plots and archive")
    sector_out.add_argument(
        "--plots",
        action="store_true",
        help="also draw the scatter and bar plots as PNGs, as R does (needs matplotlib)",
    )
    sector_out.add_argument(
        "--zip", action="store_true", help="also zip OUT/NAME/corr/ to OUT/NAME_corr.zip, as R"
    )
    sector.add_argument("--progress", action="store_true", help=_PROGRESS_HELP)

    commands.add_parser(
        "modules",
        help="list the QC, homogeneity and index modules available",
        description="List the built-in modules and the plugins installed through the "
        "climpact.qc, climpact.homogeneity and climpact.indices entry points, with the "
        "options each takes.",
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
        report=args.report,
    )
    archive = written.pop("zip", None)
    report = written.pop("report", None)
    print(f"Wrote {len(written)} files to {args.out / metadata.name}")
    if archive is not None:
        print(f"Zipped them to {archive}")
    if report is not None:
        print(f"Wrote the report to {report}")
    if skipped:
        print(f"Not written (no data in any period): {', '.join(skipped)}")
    return 0


def _batch_report_dir(out: Path) -> Path:
    """``OUT_reports`` next to the batch folder, so the batch zip keeps R's layout."""
    return out.parent / f"{out.name}_reports"


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
        report_dir=_batch_report_dir(args.out) if args.report else None,
    )
    failed = [r for r in results if not r.ok]
    print(f"Done: {total - len(failed)} of {total} stations processed, {len(failed)} failed")
    if args.zip:
        print(f"Zipped the output folder to {args.out.parent / (args.out.name + '.zip')}")
    if args.report:
        print(f"Wrote the stations' reports to {_batch_report_dir(args.out)}")
    for result in failed:
        print(f"  {result.name}: see {result.error_file}")
    return 1 if failed else 0


def gridded_thresholds_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from climpact.gridded import open_grid, write_grid_thresholds
    from climpact.thresholds import InsufficientBaseData

    input_files = _input_files(args, parser)
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if args.base_end < args.base_start:
        parser.error("--base-end is before --base-start")
    if args.tmp_dir is not None and not args.tmp_dir.is_dir():
        parser.error(f"--tmp-dir is not a directory: {args.tmp_dir}")
    try:
        inp = open_grid(input_files, **_open_grid_args(args))
    except (ValueError, NotImplementedError) as exc:
        parser.error(str(exc))
    author = {"institution": args.institution, "institution_id": args.institution_id}
    ny, nx = inp.shape
    progress = _grid_progress(args)

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


def gridded_indices_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from dataclasses import replace

    from climpact.gridded import open_grid, write_grid_indices
    from climpact.gridded.indices import WRAPPER_PARAMS, index_files
    from climpact.thresholds import InsufficientBaseData

    input_files = _input_files(args, parser)
    if args.thresholds is not None and not args.thresholds.is_file():
        parser.error(f"thresholds file not found: {args.thresholds}")
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if args.base_end < args.base_start:
        parser.error("--base-end is before --base-start")
    params = replace(
        WRAPPER_PARAMS,
        **{
            k: getattr(args, k)
            for k in (
                "wsdi_days", "csdi_days", "rx_days", "txtn_days", "hdd_base", "cdd_base",
                "gdd_base", "rnnmm",
            )
        },
    )  # fmt: skip
    if args.indices:
        known = {f.index for f in index_files(params)}
        unknown = sorted(set(args.indices) - known)
        if unknown:
            parser.error(f"unknown indices {unknown}; known: {' '.join(sorted(known))}")
    if args.tmp_dir is not None and not args.tmp_dir.is_dir():
        parser.error(f"--tmp-dir is not a directory: {args.tmp_dir}")
    try:
        inp = open_grid(input_files, **_open_grid_args(args))
    except (ValueError, NotImplementedError) as exc:
        parser.error(str(exc))
    author = {"institution": args.institution, "institution_id": args.institution_id}
    ny, nx = inp.shape
    progress = _grid_progress(args)

    if not args.quiet:
        print(
            f"{ny} x {nx} cells, {inp.time[0]:%Y-%m-%d} to {inp.time[-1]:%Y-%m-%d}, "
            f"base period {args.base_start}-{args.base_end}"
            + (f", thresholds from {args.thresholds}" if args.thresholds else "")
        )
    try:
        paths = write_grid_indices(
            inp,
            args.out,
            args.base_start,
            args.base_end,
            template=args.template,
            params=params,
            thresholds_file=args.thresholds,
            author=author,
            workers=args.workers,
            progress=progress,
            indices=args.indices,
        )
    except (InsufficientBaseData, ValueError) as exc:
        parser.error(str(exc))
    print(f"Wrote {len(paths)} files to {args.out}")
    if args.trends:
        from climpact.gridded.trends import TRENDS_FILE, write_grid_trends

        def trend_progress(stage: str, done: int, total: int) -> None:
            if not args.quiet:
                print(f"[{done}/{total}] trends", flush=True)

        trends = write_grid_trends(
            paths,
            args.out / TRENDS_FILE,
            args.base_start,
            args.base_end,
            latitude=inp.cell_latitude().values,
            workers=args.workers,
            progress=trend_progress,
        )
        print(f"Wrote {trends}" if trends else "No annual index: trends.nc not written")
    return 0


def sector_correlation_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from climpact.sector import SectorCorrelationError, corr_dir, run_sector_correlation

    for path in (args.station_file, args.sector_file):
        if not path.is_file():
            parser.error(f"file not found: {path}")
    name = args.name or args.station_file.stem
    if not (args.out / name / "indices").is_dir():
        parser.error(f"no indices in {args.out / name}: run `climpact run` first")
    _plots_available(args, parser)
    progress = None
    if args.progress:

        def progress(stage: str, step: int, total: int) -> None:
            _print_stage("", stage, step, total)

    try:
        written = run_sector_correlation(
            args.station_file,
            args.sector_file,
            args.out,
            name,
            detrend_sector=not args.no_detrend,
            title=args.title,
            y_label=args.y_label,
            plots=args.plots,
            zip=args.zip,
            progress=progress,
        )
    except SectorCorrelationError as exc:
        print(f"climpact sector-correlation: error: {exc}", file=sys.stderr)
        return 1
    archive = written.pop("zip", None)
    print(f"Wrote {len(written)} files to {corr_dir(args.out, name)}")
    if archive is not None:
        print(f"Zipped them to {archive}")
    return 0


def _describe_option(option) -> str:
    text = f"{option.name} ({option.type.__name__}"
    text += ", required)" if option.required else f", default {option.default!r})"
    if option.choices is not None:
        text += f" one of {', '.join(map(str, option.choices))}"
    return f"{text}: {option.help}" if option.help else text


def modules_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from climpact.modules import available, load, module_options

    for kind in KINDS:
        print(f"{kind}:")
        for name, source in available(kind).items():
            print(f"  {name} ({source})")
            try:
                options = module_options(load(kind, name))
            except Exception as exc:  # a broken plugin should not hide the others
                print(f"    cannot load: {exc}")
                continue
            for option in options:
                print(f"    {_describe_option(option)}")
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
    if args.command == "gridded-indices":
        return gridded_indices_command(args, parser)
    if args.command == "sector-correlation":
        return sector_correlation_command(args, parser)
    parser.error(f"unknown command {args.command!r}")  # pragma: no cover
    return 2


if __name__ == "__main__":
    sys.exit(main())
