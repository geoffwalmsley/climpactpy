"""Pluggable QC, homogeneity and index modules, and the pipeline that chains them.

A station run goes through three stages::

    input -> QC modules -> homogeneity module (optional) -> index modules

- A **QC module** (:class:`QCModule`) reports on the input data. It does not change it.
  The built-in one, ``climpact``, writes R's ``qc/`` files.
- A **homogeneity module** (:class:`HomogeneityModule`) checks the series for breaks. It
  returns tables (for example a breaks table) and, optionally, adjusted data. When it
  returns adjusted data, the index modules use it. The QC tables and the returned
  :class:`PipelineResult` keep the original. At most one homogeneity module runs. The
  built-in ``none`` passes the data through.
- An **index module** (:class:`IndexModule`) calculates indices. The built-in one,
  ``climpact``, writes R's ``indices/``, ``thres/`` and ``trend/`` files.

``run_pipeline`` takes an optional progress callback (see :mod:`climpact.progress`),
called after each module. A module may report finer steps: it then has a method
``progress_steps()`` returning the names of its steps, and its ``build`` (or
``homogenise``) takes a keyword argument ``progress``, a callable it calls with the name
of each step as the step finishes. The built-in index module reports each index product
this way. The protocols below do not require either.

Every module returns ``{output key: DataFrame}``, as the products in
:mod:`climpact.outputs` do. Keys are ``<folder>/<name>`` and are written to
``<out>/<station>/<folder>/<station>_<name>.csv``. A key may be produced once per run.
Tables of third-party modules must carry a :class:`~climpact.io.output_files.FileFormat`
(:func:`~climpact.io.output_files.with_file_format`), since ``write_outputs`` knows the
layouts of the built-in files only.

Third-party modules are found through the entry point groups ``climpact.qc``,
``climpact.homogeneity`` and ``climpact.indices``. An entry point names a module object,
or a class that is called with no arguments to make one; the entry point name is the
module name used to select it. Built-in modules are always available. Installed plugins
run only when selected (:class:`ModuleSelection`), so installing one does not change
what a run writes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from importlib.metadata import entry_points
from typing import Literal, Protocol, runtime_checkable

import pandas as pd
import xarray as xr

from climpact.io.output_files import FILE_FORMAT_ATTR
from climpact.progress import Progress, Steps
from climpact.station import StationRun

Kind = Literal["qc", "homogeneity", "indices"]
KINDS: tuple[Kind, ...] = ("qc", "homogeneity", "indices")
ENTRY_POINT_GROUPS: dict[Kind, str] = {kind: f"climpact.{kind}" for kind in KINDS}

Tables = Mapping[str, pd.DataFrame]


@runtime_checkable
class QCModule(Protocol):
    """Reports on a run's input data. It must not change the run."""

    name: str

    def build(self, run: StationRun, tables: Tables) -> Tables:
        """Return ``{output key: table}``. ``tables`` holds the earlier modules' tables."""
        ...


@dataclass(frozen=True)
class HomogeneityResult:
    """What a homogeneity module returns.

    ``tables`` are written like any other output (for example ``homogeneity/breaks``).
    ``data`` is the adjusted series the indices are calculated from: a copy of
    ``run.data`` with the same time axis and variables and some values changed. None:
    the data is not changed.
    """

    tables: Tables = field(default_factory=dict)
    data: xr.Dataset | None = None


@runtime_checkable
class HomogeneityModule(Protocol):
    """Checks a run's series for inhomogeneities and may return adjusted data."""

    name: str

    def homogenise(self, run: StationRun, tables: Tables) -> HomogeneityResult:
        """Check ``run``. ``tables`` holds the QC tables."""
        ...


@runtime_checkable
class IndexModule(Protocol):
    """Calculates indices from a run (the adjusted data when there is any)."""

    name: str

    def build(self, run: StationRun, tables: Tables) -> Tables:
        """Return ``{output key: table}``. ``tables`` holds the earlier modules' tables."""
        ...


class PassThrough:
    """The ``none`` homogeneity module: no tables, data unchanged."""

    name = "none"

    def homogenise(self, run: StationRun, tables: Tables) -> HomogeneityResult:
        return HomogeneityResult()


PASS_THROUGH = PassThrough()


DEFAULT_QC = ("climpact",)
DEFAULT_HOMOGENEITY = "none"
DEFAULT_INDICES = ("climpact",)


@dataclass(frozen=True)
class ModuleSelection:
    """The modules a run uses, by name, in the order they run.

    Names only, so a selection can be sent to the batch worker processes; each process
    looks the modules up itself (:func:`resolve`). The defaults are the built-in modules,
    which reproduce Climpact R's outputs.
    """

    qc: tuple[str, ...] = DEFAULT_QC
    homogeneity: str = DEFAULT_HOMOGENEITY
    indices: tuple[str, ...] = DEFAULT_INDICES


class UnknownModuleError(LookupError):
    """A selected module is neither built in nor installed."""


def _builtin(kind: Kind) -> dict[str, object]:
    if kind == "qc":
        from climpact.products.qc import CLIMPACT_QC

        return {CLIMPACT_QC.name: CLIMPACT_QC}
    if kind == "homogeneity":
        return {PASS_THROUGH.name: PASS_THROUGH}
    from climpact.outputs import CLIMPACT_INDICES

    return {CLIMPACT_INDICES.name: CLIMPACT_INDICES}


_PROTOCOLS: dict[Kind, type] = {
    "qc": QCModule,
    "homogeneity": HomogeneityModule,
    "indices": IndexModule,
}


def available(kind: Kind) -> dict[str, str]:
    """Names of the modules of ``kind``: ``{name: "built-in" or the entry point value}``.

    Plugins are listed without being imported.
    """
    names = dict.fromkeys(_builtin(kind), "built-in")
    for ep in entry_points(group=ENTRY_POINT_GROUPS[kind]):
        names.setdefault(ep.name, ep.value)
    return names


def load(kind: Kind, name: str) -> object:
    """The module of ``kind`` called ``name``: built in, else from its entry point."""
    builtin = _builtin(kind)
    if name in builtin:
        return builtin[name]
    matches = [ep for ep in entry_points(group=ENTRY_POINT_GROUPS[kind]) if ep.name == name]
    if not matches:
        known = ", ".join(sorted(available(kind)))
        raise UnknownModuleError(f"no {kind} module named {name!r} (available: {known})")
    if len(matches) > 1:
        sources = ", ".join(ep.value for ep in matches)
        raise UnknownModuleError(f"{kind} module {name!r} is installed twice: {sources}")
    module = matches[0].load()
    if isinstance(module, type):
        module = module()
    if not isinstance(module, _PROTOCOLS[kind]):
        raise TypeError(
            f"{kind} module {name!r} ({matches[0].value}) does not implement "
            f"{_PROTOCOLS[kind].__name__}"
        )
    return module


@dataclass(frozen=True)
class Modules:
    """Selected modules, loaded."""

    qc: tuple[QCModule, ...]
    homogeneity: HomogeneityModule
    indices: tuple[IndexModule, ...]


def resolve(selection: ModuleSelection | None = None) -> Modules:
    """Load the modules of ``selection`` (default: the built-in ones).

    Raises :class:`UnknownModuleError` for a name that is not available.
    """
    selection = selection or ModuleSelection()
    return Modules(
        qc=tuple(load("qc", name) for name in selection.qc),
        homogeneity=load("homogeneity", selection.homogeneity),
        indices=tuple(load("indices", name) for name in selection.indices),
    )


@dataclass(frozen=True)
class PipelineResult:
    """Every table of a run, with the run QC saw and the run the indices used.

    ``indices_run`` is ``input_run`` itself unless the homogeneity module returned
    adjusted data.
    """

    tables: dict[str, pd.DataFrame]
    input_run: StationRun
    indices_run: StationRun

    @property
    def adjusted(self) -> bool:
        return self.indices_run is not self.input_run


def _add(tables: dict[str, pd.DataFrame], new: Tables, kind: Kind, module: object) -> None:
    builtin = _builtin(kind).get(getattr(module, "name", None)) is module
    for key, table in new.items():
        if key in tables:
            raise ValueError(f"output {key!r} produced twice ({kind} module {module.name!r})")
        folder, sep, name = key.partition("/")
        if not (folder and sep and name):
            raise ValueError(
                f"{kind} module {module.name!r}: output key {key!r} is not folder/name"
            )
        if not builtin and FILE_FORMAT_ATTR not in table.attrs:
            raise ValueError(
                f"{kind} module {module.name!r}: output {key!r} has no FileFormat "
                "(attach one with climpact.io.output_files.with_file_format)"
            )
        tables[key] = table


def _adjusted_run(run: StationRun, data: xr.Dataset, module: HomogeneityModule) -> StationRun:
    """``run`` with the homogeneity module's adjusted data."""
    if not data["time"].equals(run.data["time"]):
        raise ValueError(f"homogeneity module {module.name!r} changed the time axis")
    missing = [v for v in run.data.data_vars if v not in data.data_vars]
    if missing:
        raise ValueError(f"homogeneity module {module.name!r} dropped {', '.join(missing)}")
    # Keep the station attributes (first_date, last_date, ...) the products read.
    data = data.assign_attrs({**run.data.attrs, **data.attrs})
    # A new StationRun, so the thresholds are computed from the adjusted data. QC has run,
    # so the merged QC rows are not carried over.
    return replace(run, data=data, qc_rows=None)


def _steps(kind: Kind, module: object) -> list[str]:
    """The progress stages of ``module``: its own steps if it reports them, else one."""
    prefix = f"{kind}:{module.name}"
    own = getattr(module, "progress_steps", None)
    if callable(own):
        return [f"{prefix}:{step}" for step in own()]
    return [prefix]


def pipeline_stages(modules: Modules | ModuleSelection | None = None) -> list[str]:
    """The stages ``run_pipeline`` reports to its progress callback, in order."""
    if not isinstance(modules, Modules):
        modules = resolve(modules)
    return [
        *(stage for module in modules.qc for stage in _steps("qc", module)),
        *_steps("homogeneity", modules.homogeneity),
        *(stage for module in modules.indices for stage in _steps("indices", module)),
    ]


def _call(method, kind: Kind, module: object, steps: Steps, *args):
    """Call ``module``'s ``method`` and report its progress stages."""
    prefix = f"{kind}:{module.name}"
    if steps.progress is not None and callable(getattr(module, "progress_steps", None)):
        return method(*args, progress=lambda step: steps.done(f"{prefix}:{step}"))
    result = method(*args)
    steps.done(prefix)
    return result


def run_pipeline(
    run: StationRun,
    modules: Modules | ModuleSelection | None = None,
    progress: Progress | None = None,
) -> PipelineResult:
    """Run QC, homogeneity and index modules on ``run`` and collect their tables.

    ``progress(stage, step, total)`` is called as each stage of :func:`pipeline_stages`
    finishes (see :mod:`climpact.progress`).
    """
    if not isinstance(modules, Modules):
        modules = resolve(modules)
    steps = Steps(progress, len(pipeline_stages(modules)) if progress else 0)
    tables: dict[str, pd.DataFrame] = {}
    for module in modules.qc:
        _add(tables, _call(module.build, "qc", module, steps, run, dict(tables)), "qc", module)

    homogeneity = _call(
        modules.homogeneity.homogenise,
        "homogeneity",
        modules.homogeneity,
        steps,
        run,
        dict(tables),
    )
    _add(tables, homogeneity.tables, "homogeneity", modules.homogeneity)
    indices_run = run
    if homogeneity.data is not None:
        indices_run = _adjusted_run(run, homogeneity.data, modules.homogeneity)

    for module in modules.indices:
        new = _call(module.build, "indices", module, steps, indices_run, dict(tables))
        _add(tables, new, "indices", module)
    return PipelineResult(tables, run, indices_run)
