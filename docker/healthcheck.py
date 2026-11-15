#!/opt/venv/bin/python
"""Docker HEALTHCHECK of the climpact-web image (#120).

For the ``web`` role, GET ``/healthz`` on the local server: healthy when it answers 200
(the app is up and the database answers). Django checks the Host header against
``CLIMPACT_WEB_ALLOWED_HOSTS``, so the request uses the first allowed host name. Other
roles (worker, one-off commands) have no server and always count as healthy; the role is
read from PID 1's command line, which the entrypoint exec's.
"""

import os
import sys
import urllib.request
from pathlib import Path


def main() -> int:
    try:
        cmdline = Path("/proc/1/cmdline").read_bytes().split(b"\0")
    except OSError:
        cmdline = []
    if b"manage" in cmdline:  # worker or a one-off command: no web server to check
        return 0
    hosts = [h.strip() for h in os.environ.get("CLIMPACT_WEB_ALLOWED_HOSTS", "").split(",")]
    host = next((h.lstrip(".") for h in hosts if h and h != "*"), "localhost")
    port = os.environ.get("CLIMPACT_WEB_PORT", "8000")
    request = urllib.request.Request(f"http://127.0.0.1:{port}/healthz", headers={"Host": host})
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            return 0 if response.status == 200 else 1
    except Exception as exc:  # any failure, including 503, is unhealthy
        print(f"unhealthy: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
