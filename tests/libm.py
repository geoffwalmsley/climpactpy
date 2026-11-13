"""Whether this platform's C maths library is the one the R reference was made with.

SPI and SPEI pass values through the C library's ``exp``, ``log``, ``log1p``, ``pow``,
``sin``, ``cos``, ``tan`` and ``acos`` (Python's ``math`` module calls the same
functions R does). The R reference outputs were made with glibc on x86_64; there the
port reproduces R bit for bit. Other C libraries, such as macOS's, return a different
last bit for some inputs (and glibc itself is not always correctly rounded, so no
portable implementation can match it everywhere), which can change the 15th significant
digit of an SPI or SPEI value. Tests that compare these values exactly relax to a
tolerance of ``LIBM_RTOL`` relative plus ``LIBM_ATOL`` on other platforms.
"""

from __future__ import annotations

import platform
import sys

GLIBC_X86_64 = (
    sys.platform.startswith("linux")
    and platform.machine() in ("x86_64", "AMD64")
    and platform.libc_ver()[0] == "glibc"
)
LIBM_RTOL = 1e-10
LIBM_ATOL = 1e-12
