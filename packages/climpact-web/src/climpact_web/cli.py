"""The ``climpact-web`` command.

``climpact-web`` starts the app for one user on their own computer (local mode): it
prepares the data folder (database, secret key, run files), applies database migrations,
serves the app with waitress on localhost and opens it in the browser. Everything it
needs ships in the package, so it works without a network connection.

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
import sys
import threading
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


def manage(argv: list[str]) -> int:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", SETTINGS_MODULE)
    from django.core.management import execute_from_command_line

    execute_from_command_line(["climpact-web manage", *argv])
    return 0


def _stop(signum, frame):
    raise KeyboardInterrupt


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

    options = {
        "host": args.host,
        "threads": args.threads,
        "max_request_body_size": settings.MAX_UPLOAD_BYTES,
        "ident": "climpact-web",
    }
    app = get_wsgi_application()
    if args.port is not None:
        server = create_server(app, port=args.port, **options)
    else:
        try:
            server = create_server(app, port=DEFAULT_PORT, **options)
        except OSError:  # the default port is taken: let the system pick a free one
            server = create_server(app, port=0, **options)
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
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "manage":
        return manage(argv[1:])
    return serve(build_parser().parse_args(argv))
