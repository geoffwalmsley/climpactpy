#!/usr/bin/env python3
"""The deploy hook of climpact.app (#126): the release workflow's way in.

Runs as the `deploy-hook` service of deploy/compose.yaml (plain Python, standard library
only, no privileges, no route out). The tunnel sends https://climpact.app/_deploy here.

    POST /_deploy
    X-Climpact-Timestamp: <unix seconds>
    X-Climpact-Signature: sha256=<hex HMAC-SHA256 of "<timestamp>.<body>">
    {"version": "X.Y.Z"}

The key is DEPLOY_WEBHOOK_SECRET (in /opt/climpact/.env, and the GitHub secret of the
same name). A missing or wrong signature, or a timestamp more than five minutes off, gets
401 and changes nothing. Of the body only "version" is read, and it must be X.Y.Z (ASCII
digits). A valid request writes the version to the file `request` in the drop folder
(/run/hook, the host's /opt/climpact/hook) and answers 202 at once. It starts nothing
itself: on the host, the systemd path unit climpact-deploy.path sees the file and runs
`update.sh --hook`, one deploy at a time (a request made during a deploy waits for it,
and the latest request wins). So this process can ask for a release to be deployed and do
nothing else. Every answer is JSON with "hook": "climpact-deploy" (so a caller can tell
the hook from the app), Cache-Control: no-store and a Content-Security-Policy that allows
nothing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import signal
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PATH = "/_deploy"
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+", re.ASCII)
MAX_BODY = 1024  # bytes; the real body is about 20
MAX_SKEW = 300  # seconds between the caller's clock and ours
MIN_SECRET = 32  # characters; `openssl rand -hex 32` gives 64
TIMEOUT = 10  # seconds a connection may take to send its request


def signature(secret: str, timestamp: str, body: bytes) -> str:
    """The X-Climpact-Signature value for a request (also used by the tests)."""
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


class Hook(BaseHTTPRequestHandler):
    server_version = "climpact-deploy-hook"
    sys_version = ""
    timeout = TIMEOUT

    # Set on the class by make_server().
    secret: str = ""
    drop: Path = Path("/run/hook")
    clock = staticmethod(time.time)

    def answer(self, status: int, reason: str, **extra) -> None:
        body = json.dumps({"hook": "climpact-deploy", "status": reason, **extra}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        # JSON only: nothing to load, nothing may frame it (the app's own policy, #137,
        # comes from Django, which this process doesn't run).
        self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if status == 405:
            self.send_header("Allow", "POST")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        client = self.headers.get("CF-Connecting-IP") or self.client_address[0]
        print(f"{self.command} {self.path[:80]!r} from {client}: {status} {reason}", flush=True)

    def log_message(self, format, *args):  # noqa: A002 - one line per request in answer()
        pass

    def not_post(self) -> None:
        if self.path.split("?", 1)[0] != PATH:
            self.answer(404, "not found")
        else:
            self.answer(405, "POST only")

    do_GET = do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = not_post

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != PATH:
            return self.answer(404, "not found")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self.answer(411, "Content-Length required")
        if length < 0 or length > MAX_BODY:
            return self.answer(413, "body too large")
        body = self.rfile.read(length)
        if len(self.secret) < MIN_SECRET:
            return self.answer(503, "DEPLOY_WEBHOOK_SECRET is not set (or too short) on the server")
        timestamp = self.headers.get("X-Climpact-Timestamp", "")
        given = self.headers.get("X-Climpact-Signature", "")
        if not timestamp.isascii() or not timestamp.isdigit():
            return self.answer(401, "bad signature")
        if abs(self.clock() - int(timestamp)) > MAX_SKEW:
            return self.answer(401, "bad signature (timestamp too old or in the future)")
        if not hmac.compare_digest(
            given.encode(), signature(self.secret, timestamp, body).encode()
        ):
            return self.answer(401, "bad signature")
        try:
            version = json.loads(body).get("version")
        except (ValueError, AttributeError):
            version = None
        if not isinstance(version, str) or not VERSION.fullmatch(version):
            return self.answer(400, 'the body must be {"version": "X.Y.Z"}')
        try:
            tmp = self.drop / ".request.tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
            with os.fdopen(fd, "w") as f:
                f.write(version + "\n")
            os.replace(tmp, self.drop / "request")
        except OSError as exc:
            print(f"cannot write to {self.drop}: {exc}", file=sys.stderr, flush=True)
            return self.answer(500, "cannot queue the deploy; see the hook's log")
        return self.answer(202, "accepted", version=version)


def make_server(host: str, port: int, secret: str, drop: Path) -> ThreadingHTTPServer:
    handler = type("ConfiguredHook", (Hook,), {"secret": secret, "drop": drop})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def main() -> int:
    secret = os.environ.get("DEPLOY_WEBHOOK_SECRET", "").strip()
    drop = Path(os.environ.get("DEPLOY_HOOK_DIR", "/run/hook"))
    port = int(os.environ.get("DEPLOY_HOOK_PORT", "9000"))
    if len(secret) < MIN_SECRET:
        print(
            f"DEPLOY_WEBHOOK_SECRET is missing or shorter than {MIN_SECRET} characters: "
            "every request gets 503 (set it in /opt/climpact/.env, then docker compose up -d)",
            file=sys.stderr,
            flush=True,
        )
    if not os.access(drop, os.W_OK):
        print(
            f"{drop} is not writable: run `sudo /opt/climpact/update.sh --install-hook` once",
            file=sys.stderr,
            flush=True,
        )
    server = make_server("0.0.0.0", port, secret, drop)
    # PID 1 in its container: without a handler, SIGTERM (docker stop) would be ignored.
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))
    print(f"deploy hook listening on :{port}, POST {PATH}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
