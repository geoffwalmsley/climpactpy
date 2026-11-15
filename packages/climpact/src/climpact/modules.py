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

A module may take **options** (:class:`Option`): it lists them in an ``options``
attribute, and its ``build`` (or ``homogenise``) then takes a keyword argument
``options``, a dict holding a value for every option it declares (the user's value, else
the default). Options are chosen per module in :attr:`ModuleSelection.options` and are
checked by :func:`resolve` (:class:`ModuleOptionError`), so a bad option fails before
any station runs. Modules without an ``options`` attribute take none; the built-in
modules take none.

Third-party modules are found through the entry point groups ``climpact.qc``,
``climpact.homogeneity`` and ``climpact.indices``. An entry point names a module object,
or a class that is called with no arguments to make one; the entry point name is the
module name used to select it. Built-in modules are always available. Installed plugins
run only when selected (:class:`ModuleSelection`), so installing one does not change
what a run writes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from importlib.metadata import entry_points
from typing import Any, Literal, Protocol, runtime_checkable

import pandas as pd
import xarray as xr

from climpact.io.output_files import FILE_FORMAT_ATTR
from climpact.progress import Progress, Steps
from climpact.station import StationRun

Kind = Literal["qc", "homogeneity", "indices"]
KINDS: tuple[Kind, ...] = ("qc", "homogeneity", "indices")
ENTRY_POINT_GROUPS: dict[Kind, str] = {kind: f"climpact.{kind}" for kind in KINDS}

Tables = Mapping[str, pd.DataFrame]

OptionValues = Mapping[str, Any]
"""``{option name: value}`` for one module."""

OPTION_TYPES: tuple[type, ...] = (str, int, float, bool)
_TRUE = ("true", "yes", "on", "1")
_FALSE = ("false", "no", "off", "0")


class ModuleOptionError(ValueError):
    """A module option is unknown, missing or has an invalid value."""


@dataclass(frozen=True)
class Option:
    """An option a module accepts.

    ``type`` is ``str``, ``int``, ``float`` or ``bool``. ``default`` is used when the
    user gives no value (``required`` options have none). ``choices``, if given, are the
    only values allowed. ``help`` is shown by ``climpact modules``.
    """

    name: str
    type: type = str
    default: Any = None
    help: str = ""
    choices: tuple[Any, ...] | None = None
    required: bool = False

    def __post_init__(self) -> None:
        if self.type not in OPTION_TYPES:
            raise TypeError(f"option {self.name!r}: type must be str, int, float or bool")
        if not self.name.isidentifier():
            raise ValueError(f"option name {self.name!r} is not an identifier")

    def convert(self, value: Any) -> Any:
        """``value`` checked and converted to the option's type.

        Strings (from the command line) are parsed; other values must already have the
        option's type (an int is accepted for a float option). Raises ``ValueError``.
        """
        if isinstance(value, str) and self.type is not str:
            value = self._parse(value)
        elif self.type is float and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        elif not isinstance(value, self.type) or (self.type is int and isinstance(value, bool)):
            raise ValueError(f"expected {self.type.__name__}, got {value!r}")
        if self.choices is not None and value not in self.choices:
            allowed = ", ".join(map(str, self.choices))
            raise ValueError(f"{value!r} is not one of {allowed}")
        return value

    def _parse(self, text: str) -> Any:
        if self.type is bool:
            if text.strip().lower() in _TRUE:
                return True
            if text.strip().lower() in _FALSE:
                return False
            raise ValueError(f"expected true or false, got {text!r}")
        try:
            return self.type(text)
        except ValueError:
            raise ValueError(f"expected {self.type.__name__}, got {text!r}") from None


def module_options(module: object) -> tuple[Option, ...]:
    """The options ``module`` declares (none if it has no ``options`` attribute)."""
    declared = getattr(module, "options", None)
    if declared is None:
        return ()
    if isinstance(declared, str | bytes) or not isinstance(declared, Sequence):
        raise TypeError(f"module {module.name!r}: options must be a sequence of Option")
    if not all(isinstance(o, Option) for o in declared):
        raise TypeError(f"module {module.name!r}: options must be a sequence of Option")
    return tuple(declared)


def option_values(kind: Kind, module: object, given: OptionValues | None) -> dict[str, Any]:
    """Every option of ``module`` with its value: ``given``, else the default.

    Raises :class:`ModuleOptionError` for an unknown option, a missing required one or an
    invalid value.
    """
    declared = {o.name: o for o in module_options(module)}
    given = dict(given or {})
    label = f"{kind} module {module.name!r}"
    unknown = sorted(set(given) - set(declared))
    if unknown:
        accepted = ", ".join(declared) if declared else "none"
        raise ModuleOptionError(f"{label} has no option {unknown[0]!r} (options: {accepted})")
    values = {}
    for name, option in declared.items():
        if name not in given:
            if option.required:
                raise ModuleOptionError(f"{label}: option {name!r} is required")
            values[name] = option.default
            continue
        try:
            values[name] = option.convert(given[name])
        except ValueError as exc:
            raise ModuleOptionError(f"{label}: option {name!r}: {exc}") from None
    return values


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
    """The modules a run uses, by name, in the order they run, and their options.

    Names and plain values only, so a selection can be sent to the batch worker
    processes; each process looks the modules up itself (:func:`resolve`). The defaults
    are the built-in modules, which reproduce Climpact R's outputs.

    ``options`` is ``{kind: {module name: {option name: value}}}``, for example
    ``{"homogeneity": {"example_shift": {"adjustment": 2.0}}}``. Values may be strings,
    which are parsed to the option's type. Options not given take their defaults.
    """

    qc: tuple[str, ...] = DEFAULT_QC
    homogeneity: str = DEFAULT_HOMOGENEITY
    indices: tuple[str, ...] = DEFAULT_INDICES
    options: Mapping[str, Mapping[str, OptionValues]] = field(default_factory=dict)

    def names(self, kind: Kind) -> tuple[str, ...]:
        """The selected modules of ``kind``."""
        if kind == "homogeneity":
            return (self.homogeneity,)
        return self.qc if kind == "qc" else self.indices


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
    """Selected modules, loaded, and their checked options.

    ``options`` maps ``(kind, module name)`` to the module's option values, for the
    modules that declare options.
    """

    qc: tuple[QCModule, ...]
    homogeneity: HomogeneityModule
    indices: tuple[IndexModule, ...]
    options: Mapping[tuple[Kind, str], dict[str, Any]] = field(default_factory=dict)


def _check_option_keys(selection: ModuleSelection) -> None:
    """Options are given only for kinds and modules that are selected."""
    if not isinstance(selection.options, Mapping):
        raise ModuleOptionError("module options must be {kind: {module: {option: value}}}")
    for kind, by_module in selection.options.items():
        if kind not in KINDS:
            raise ModuleOptionError(
                f"module options: unknown kind {kind!r} (kinds: {', '.join(KINDS)})"
            )
        if not isinstance(by_module, Mapping):
            raise ModuleOptionError(f"module options for {kind}: expected {{module: {{...}}}}")
        for name, values in by_module.items():
            if name not in selection.names(kind):
                raise ModuleOptionError(f"options given for {kind} module {name!r}, not selected")
            if not isinstance(values, Mapping):
                raise ModuleOptionError(
                    f"options of {kind} module {name!r}: expected {{option: value}}"
                )


def resolve(selection: ModuleSelection | None = None) -> Modules:
    """Load the modules of ``selection`` (default: the built-in ones) and check options.

    Raises :class:`UnknownModuleError` for a name that is not available and
    :class:`ModuleOptionError` for a bad option.
    """
    selection = selection or ModuleSelection()
    _check_option_keys(selection)
    loaded = {kind: [load(kind, name) for name in selection.names(kind)] for kind in KINDS}
    options: dict[tuple[Kind, str], dict[str, Any]] = {}
    for kind, found in loaded.items():
        given = selection.options.get(kind, {})
        for module in found:
            values = option_values(kind, module, given.get(module.name))
            if module_options(module):
                options[(kind, module.name)] = values
    return Modules(
        qc=tuple(loaded["qc"]),
        homogeneity=loaded["homogeneity"][0],
        indices=tuple(loaded["indices"]),
        options=options,
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


def _call(method, kind: Kind, module: object, steps: Steps, modules: Modules, *args):
    """Call ``module``'s ``method`` with its options and report its progress stages."""
    prefix = f"{kind}:{module.name}"
    kwargs = {}
    if module_options(module):
        kwargs["options"] = dict(
            modules.options.get((kind, module.name)) or option_values(kind, module, None)
        )
    if steps.progress is not None and callable(getattr(module, "progress_steps", None)):
        return method(*args, progress=lambda step: steps.done(f"{prefix}:{step}"), **kwargs)
    result = method(*args, **kwargs)
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
        _add(
            tables,
            _call(module.build, "qc", module, steps, modules, run, dict(tables)),
            "qc",
            module,
        )

    homogeneity = _call(
        modules.homogeneity.homogenise,
        "homogeneity",
        modules.homogeneity,
        steps,
        modules,
        run,
        dict(tables),
    )
    _add(tables, homogeneity.tables, "homogeneity", modules.homogeneity)
    indices_run = run
    if homogeneity.data is not None:
        indices_run = _adjusted_run(run, homogeneity.data, modules.homogeneity)

    for module in modules.indices:
        new = _call(module.build, "indices", module, steps, modules, indices_run, dict(tables))
        _add(tables, new, "indices", module)
    return PipelineResult(tables, run, indices_run)
