"""One lock for every netCDF file the web app reads on its request threads (#295).

The HDF5 library in the netCDF4 wheels is not built thread-safe, and the server answers
requests on several threads (waitress): a gridded run's Map page and its PNG, values and
CSV ask for the same files at once, and two threads in HDF5 together fail ("NetCDF:
Can't open HDF5 attribute") or crash the process. So every open, read and close of a
netCDF file on a request thread holds :data:`LOCK`: :func:`dataset` opens a file under
it, and the reads that go through the core's reader or xarray (the set-up page's
pre-flight and its estimate of how the files will be read) hold it around the call. It
is reentrant, so a function holding it may call another that takes it. The jobs run in
the worker, a process of its own, and need none.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

LOCK = threading.RLock()


@contextmanager
def dataset(path: str | Path) -> Iterator:
    """``netCDF4.Dataset(path)`` opened, read and closed while holding :data:`LOCK`."""
    import netCDF4

    with LOCK:
        nc = netCDF4.Dataset(path)
        try:
            yield nc
        finally:
            nc.close()
