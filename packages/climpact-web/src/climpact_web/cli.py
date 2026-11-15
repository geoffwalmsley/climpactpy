"""The ``climpact-web`` command.

``climpact-web`` starts the app for one user on their own computer (local mode): it
prepares the data folder (database, secret key, run files), applies database migrations,
collects the static files into the data folder (hashed names, gzip and Brotli copies),
starts a background worker (a child process running ``manage runworker``, restarted if it
crashes), serves the app with waitress on localhost and opens it in the browser.
Everything it needs ships in the package, so it works without a network connection.

``climpact-web manage <command> ...`` runs a Django management command (``migrate``,
``collectstatic``, ``makemessages``, ...) with the app's settings, for hosted deployments
and development.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from platformdirs import user_data_dir

import climpact_web

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
SETTINGS_MODULE = "climpact_web.settings"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="climpact-web",
        description=(
            "Start the Climpact web app on this computer and open it in the browser. "
            "Use 'climpact-web manage <command>' to run a Django management command."
        ),
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=(
            f"address to listen on (default {DEFAULT_HOST}: this computer only; "
            "0.0.0.0 makes the app reachable from the network)"
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"port to listen on (default {DEFAULT_PORT}, or a free port if it is taken)",
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="do not open the app in a web browser"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help=(
            "folder for the database, uploads and results "
            "(default: the user data folder, or CLIMPACT_WEB_DATA_DIR)"
        ),
    )
    parser.add_argument(
        "--threads", type=int, default=4, help="number of request threads (default 4)"
    )
    parser.add_argument(
        "--no-worker",
        action="store_true",
        help="do not start the background worker (run 'climpact-web manage runworker' yourself)",
    )
    parser.add_argument("--version", action="version", version=climpact_web.__version__)
    return parser


def data_dir_from_env() -> Path:
    """The data folder, as the settings work it out (``CLIMPACT_WEB_DATA_DIR`` or the user
    data folder)."""
    value = os.environ.get("CLIMPACT_WEB_DATA_DIR", "").strip()
    return Path(value) if value else Path(user_data_dir("climpact-web", appauthor=False))


def prepare_data_dir(data_dir: Path) -> None:
    """Create the data folder and, on first start, the secret key file the settings read."""
    data_dir.mkdir(parents=True, exist_ok=True)
    key_file = data_dir / "secret_key"
    if not key_file.exists():
        key_file.write_text(secrets.token_urlsafe(50))
        key_file.chmod(0o600)


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def browser_url(host: str, port: int) -> str:
    """The address to open: a wildcard host is reached through localhost."""
    if host in {"0.0.0.0", "::", "[::]", ""}:
        host = "localhost"
    elif ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}/"


def proxy_options() -> dict:
    """waitress options for a reverse proxy in front of the server (hosted mode).

    ``CLIMPACT_WEB_TRUSTED_PROXY`` is the proxy's address, or ``*`` for any peer (only
    when nothing but the proxy can reach the server, as in the container behind
    Cloudflare's tunnel, #120). waitress then takes the scheme and the client address from
    the proxy's ``X-Forwarded-Proto`` and ``X-Forwarded-For``; without it, waitress drops
    those headers, so behind a TLS-terminating proxy every request would look like plain
    HTTP and be redirected to HTTPS again and again. Unset: no proxy is trusted.
    """
    proxy = os.environ.get("CLIMPACT_WEB_TRUSTED_PROXY", "").strip()
    if not proxy:
        return {}
    return {
        "trusted_proxy": proxy,
        "trusted_proxy_count": 1,
        "trusted_proxy_headers": {"x-forwarded-proto", "x-forwarded-for"},
        "clear_untrusted_proxy_headers": True,
    }


def manage(argv: list[str]) -> int:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", SETTINGS_MODULE)
    from django.core.management import execute_from_command_line

    execute_from_command_line(["climpact-web manage", *argv])
    return 0


def _stop(signum, frame):
    raise KeyboardInterrupt


class WorkerProcess:
    """The background worker as a child process of ``climpact-web`` (local mode).

    A child process rather than a thread: a calculation that crashes or runs out of memory
    does not take the web server with it, and the worker's imports (xclim, matplotlib)
    stay out of the server. If the worker exits unexpectedly its running job is marked
    failed and a new worker is started; :meth:`stop` asks it to stop (the running job is
    interrupted and queued again) and kills it if it has not stopped in ``timeout``
    seconds.
    """

    RESTART_DELAY = 2.0
    MAX_RESTARTS = 5  # within RESTART_WINDOW seconds, then give up
    RESTART_WINDOW = 60.0

    def __init__(self, env: dict[str, str] | None = None):
        self.env = env
        self.proc: subprocess.Popen | None = None
        self.name = ""
        self.stopping = threading.Event()
        self.restarts: list[float] = []
        self.count = 0
        self.thread = threading.Thread(target=self._watch, name="climpact-web-worker", daemon=True)

    def _spawn(self) -> None:
        self.count += 1
        self.name = f"{socket.gethostname()}:{os.getpid()}/worker-{self.count}"
        kwargs = {}
        if sys.platform == "win32":  # so stop() can send CTRL_BREAK_EVENT to it alone
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "climpact_web", "manage", "runworker", "--name", self.name],
            env=self.env,
            **kwargs,
        )

    def start(self) -> None:
        self._spawn()
        self.thread.start()

    def _watch(self) -> None:
        from django.db import connections

        from climpact_web.jobs.worker import release_jobs_of

        while True:
            code = self.proc.wait()
            if self.stopping.is_set():
                return
            print(
                f"The background worker stopped unexpectedly (exit status {code}).", file=sys.stderr
            )
            try:
                release_jobs_of(self.name, crashed=True)
            finally:
                connections.close_all()
            now = time.monotonic()
            self.restarts = [t for t in self.restarts if now - t < self.RESTART_WINDOW] + [now]
            if len(self.restarts) > self.MAX_RESTARTS:
                print("The background worker keeps stopping; not restarting it.", file=sys.stderr)
                return
            if self.stopping.wait(self.RESTART_DELAY):
                return
            self._spawn()

    def stop(self, timeout: float = 15.0) -> None:
        from climpact_web.jobs.worker import release_jobs_of

        self.stopping.set()
        if self.proc is None:
            return
        if self.proc.poll() is None:
            if sys.platform == "win32":
                self.proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self.proc.terminate()  # SIGTERM: interrupt the job at its next step
            try:
                self.proc.wait(timeout)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        release_jobs_of(self.name, crashed=False)  # a job still marked running: queue it again


def serve(args: argparse.Namespace) -> int:
    if args.data_dir is not None:
        os.environ["CLIMPACT_WEB_DATA_DIR"] = str(args.data_dir.expanduser().resolve())
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", SETTINGS_MODULE)
    hosted = os.environ.get("CLIMPACT_WEB_MODE", "local").strip().lower() == "hosted"

    if not hosted:
        prepare_data_dir(data_dir_from_env())
        if not is_loopback(args.host) and not os.environ.get("CLIMPACT_WEB_ALLOWED_HOSTS"):
            print(
                f"Warning: listening on {args.host}, so other computers on the network can "
                "use this app.",
                file=sys.stderr,
            )
            os.environ["CLIMPACT_WEB_ALLOWED_HOSTS"] = "*"

    import django
    from django.conf import settings
    from django.core.management import call_command
    from django.core.wsgi import get_wsgi_application
    from waitress import create_server

    django.setup()
    if not hosted:
        call_command("migrate", interactive=False, verbosity=0)
        settings.RUNS_DIR.mkdir(parents=True, exist_ok=True)
        if not settings.DEBUG:  # hashed, compressed static files (#82); a fraction of a second
            call_command("collectstatic", interactive=False, verbosity=0)

    options = {
        "host": args.host,
        "threads": args.threads,
        "max_request_body_size": max(settings.MAX_UPLOAD_BYTES, settings.GRIDDED_MAX_UPLOAD_BYTES),
        "ident": "climpact-web",
        **proxy_options(),
    }
    app = get_wsgi_application()
    if args.port is not None:
        server = create_server(app, port=args.port, **options)
    else:
        try:
            server = create_server(app, port=DEFAULT_PORT, **options)
        except OSError:  # the default port is taken: let the system pick a free one
            server = create_server(app, port=0, **options)
    worker = None
    if not hosted and not args.no_worker:
        worker = WorkerProcess()
        worker.start()
    port = getattr(server, "effective_port", None) or server.effective_listen[0][1]
    url = browser_url(args.host, port)

    print(f"Climpact web is running at {url}", flush=True)
    print(f"Data folder: {settings.DATA_DIR}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    signal.signal(signal.SIGTERM, _stop)  # stop cleanly when terminated, as on Ctrl+C
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        if worker is not None:
            worker.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "manage":
        return manage(argv[1:])
    return serve(build_parser().parse_args(argv))
