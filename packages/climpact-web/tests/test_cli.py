"""The climpact-web command."""

import os
import sqlite3
import subprocess
import sys
import time
import urllib.request

import pytest

from climpact_web import cli


def test_parser_defaults():
    args = cli.build_parser().parse_args([])
    assert (args.host, args.port, args.no_browser, args.data_dir) == (
        "127.0.0.1",
        None,
        False,
        None,
    )
    args = cli.build_parser().parse_args(["--port", "9000", "--no-browser", "--host", "::1"])
    assert (args.host, args.port, args.no_browser) == ("::1", 9000, True)


@pytest.mark.parametrize(
    "host, loopback",
    [("127.0.0.1", True), ("localhost", True), ("::1", True), ("0.0.0.0", False)],
)
def test_is_loopback(host, loopback):
    assert cli.is_loopback(host) is loopback


def test_browser_url():
    assert cli.browser_url("127.0.0.1", 8000) == "http://127.0.0.1:8000/"
    assert cli.browser_url("0.0.0.0", 8000) == "http://localhost:8000/"
    assert cli.browser_url("::1", 8001) == "http://[::1]:8001/"


def test_prepare_data_dir(tmp_path):
    data = tmp_path / "a" / "b"
    cli.prepare_data_dir(data)
    key = (data / "secret_key").read_text()
    assert len(key) > 40
    assert (data / "secret_key").stat().st_mode & 0o077 == 0
    cli.prepare_data_dir(data)  # a second start keeps the key
    assert (data / "secret_key").read_text() == key


def test_serves_local_mode(tmp_path):
    """Start `climpact-web --no-browser` on a free port, fetch pages, stop it."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLIMPACT_WEB_")}
    env.pop("DJANGO_SETTINGS_MODULE", None)
    data = tmp_path / "data"
    proc = subprocess.Popen(
        [sys.executable, "-m", "climpact_web", "--no-browser", "--port", "0"]
        + ["--data-dir", str(data)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    try:
        deadline = time.monotonic() + 60
        url = None
        output = []
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            output.append(line)
            if "is running at " in line:
                url = line.rsplit(" ", 1)[1].strip()
                break
        assert url, "".join(output)
        with urllib.request.urlopen(url + "healthz", timeout=10) as response:
            assert response.status == 200
            assert b'"status": "ok"' in response.read()
        with urllib.request.urlopen(url, timeout=10) as response:
            assert b"<html" in response.read()
        with urllib.request.urlopen(url + "static/climpact_web/css/main.css", timeout=10) as r:
            assert r.status == 200
        # The background worker was started alongside the server.
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not workers(data):
            time.sleep(0.2)
        assert len(workers(data)) == 1
    finally:
        proc.terminate()
        returncode = proc.wait(timeout=10)
        proc.stdout.close()
    assert returncode == 0  # SIGTERM stops the server cleanly
    # First start migrated the database and wrote the secret key and runs folder
    assert (data / "db.sqlite3").is_file()
    assert (data / "secret_key").is_file()
    assert (data / "media" / "runs").is_dir()
    assert workers(data) == []  # the worker was stopped cleanly too


def workers(data):
    with sqlite3.connect(data / "db.sqlite3") as con:
        return con.execute("SELECT name FROM jobs_worker").fetchall()
