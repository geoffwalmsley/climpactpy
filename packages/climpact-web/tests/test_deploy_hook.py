"""The deploy-on-release pieces in deploy/ (#126): the hook that the release workflow calls
(deploy-hook.py), the workflow's side (call-hook.sh) and the Droplet's update.sh, run with
stubbed docker and curl. Everything runs on loopback or in a temporary folder; nothing
reaches the network or Docker."""

import getpass
import http.client
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[3] / "deploy"
SECRET = "test-only-secret-" + "0" * 32  # not a real secret

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell scripts")


def load_hook():
    spec = importlib.util.spec_from_file_location("deploy_hook", DEPLOY / "deploy-hook.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = load_hook()


@pytest.fixture
def listener(tmp_path):
    """The hook on 127.0.0.1, dropping requests into tmp_path/drop."""

    def start(secret=SECRET):
        drop = tmp_path / "drop"
        drop.mkdir(exist_ok=True)
        server = hook.make_server("127.0.0.1", 0, secret, drop)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        return server.server_address[1], drop

    servers = []
    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def call(port, method="POST", path="/_deploy", body=b"", headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(method, path, body=body, headers=headers or {})
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response, json.loads(data) if data else None


def signed(version="1.2.3", secret=SECRET, timestamp=None, body=None):
    body = json.dumps({"version": version}).encode() if body is None else body
    ts = str(int(time.time()) if timestamp is None else timestamp)
    headers = {
        "Content-Type": "application/json",
        "X-Climpact-Timestamp": ts,
        "X-Climpact-Signature": hook.signature(secret, ts, body),
    }
    return body, headers


# ---- deploy-hook.py --------------------------------------------------------------------


def test_valid_request_queues_the_version(listener):
    port, drop = listener()
    body, headers = signed("1.2.3")
    response, data = call(port, body=body, headers=headers)
    assert response.status == 202
    assert data == {"hook": "climpact-deploy", "status": "accepted", "version": "1.2.3"}
    assert (drop / "request").read_text() == "1.2.3\n"
    assert response.getheader("Cache-Control") == "no-store"
    assert response.getheader("Content-Security-Policy") == (
        "default-src 'none'; frame-ancestors 'none'"
    )
    assert response.getheader("Content-Type") == "application/json"
    # A second request replaces the first: the latest one wins.
    body, headers = signed("1.2.4")
    assert call(port, body=body, headers=headers)[0].status == 202
    assert (drop / "request").read_text() == "1.2.4\n"
    assert sorted(p.name for p in drop.iterdir()) == ["request"]


@pytest.mark.parametrize(
    "case",
    ["missing", "wrong secret", "tampered body", "old timestamp", "future timestamp", "bad ts"],
)
def test_bad_signature_gets_401_and_changes_nothing(listener, case):
    port, drop = listener()
    body, headers = signed("1.2.3")
    if case == "missing":
        del headers["X-Climpact-Signature"]
    elif case == "wrong secret":
        body, headers = signed("1.2.3", secret="x" * 40)
    elif case == "tampered body":
        body = json.dumps({"version": "9.9.9"}).encode()
    elif case == "old timestamp":
        body, headers = signed("1.2.3", timestamp=int(time.time()) - hook.MAX_SKEW - 60)
    elif case == "future timestamp":
        body, headers = signed("1.2.3", timestamp=int(time.time()) + hook.MAX_SKEW + 60)
    else:
        headers["X-Climpact-Timestamp"] = "1e9"
    response, data = call(port, body=body, headers=headers)
    assert response.status == 401
    assert data["hook"] == "climpact-deploy"
    assert response.getheader("Cache-Control") == "no-store"
    assert not list(drop.iterdir())


@pytest.mark.parametrize(
    "version",
    ["1.2", "1.2.3.4", "1.2.3rc1", "v1.2.3", "1.2.3\n", " 1.2.3", "../1.2.3", "١.٢.٣", "", 123],
)
def test_only_a_plain_version_is_accepted(listener, version):
    port, drop = listener()
    body, headers = signed(version)
    response, _ = call(port, body=body, headers=headers)
    assert response.status == 400
    assert not list(drop.iterdir())


@pytest.mark.parametrize("body", [b"not json", b"[1, 2]", b'{"ref": "main"}', b"null"])
def test_a_signed_body_without_a_version_is_refused(listener, body):
    port, drop = listener()
    body, headers = signed(body=body)
    assert call(port, body=body, headers=headers)[0].status == 400
    assert not list(drop.iterdir())


def test_other_methods_paths_and_sizes(listener):
    port, drop = listener()
    response, data = call(port, "GET")
    assert response.status == 405 and response.getheader("Allow") == "POST"
    assert response.getheader("Cache-Control") == "no-store"
    assert call(port, "GET", "/")[0].status == 404
    body, headers = signed()
    assert call(port, path="/_deploy/x", body=body, headers=headers)[0].status == 404
    assert call(port, path="/healthz", body=body, headers=headers)[0].status == 404
    big = b"{" + b" " * hook.MAX_BODY + b"}"
    body, headers = signed(body=big)
    assert call(port, body=body, headers=headers)[0].status == 413
    assert not list(drop.iterdir())


@pytest.mark.parametrize("secret", ["", "short"])
def test_without_a_secret_every_request_is_refused(listener, secret):
    port, drop = listener(secret=secret)
    body, headers = signed(secret=secret or "x")
    response, data = call(port, body=body, headers=headers)
    assert response.status == 503
    assert "DEPLOY_WEBHOOK_SECRET" in data["status"]
    assert not list(drop.iterdir())


# ---- call-hook.sh (the release workflow's side) -----------------------------------------

needs_curl = pytest.mark.skipif(
    not (shutil.which("curl") and shutil.which("openssl")), reason="needs curl and openssl"
)


def call_hook(*args, **env):
    full = {**os.environ, "DEPLOY_POLL": "0", **env}
    full.pop("GITHUB_ACTIONS", None)
    return subprocess.run(
        ["sh", str(DEPLOY / "call-hook.sh"), *args],
        env=full,
        capture_output=True,
        text=True,
        timeout=60,
    )


@needs_curl
def test_call_hook_signs_the_way_the_hook_checks(listener):
    """openssl's HMAC in the workflow and Python's in the hook agree."""
    port, drop = listener()
    url = f"http://127.0.0.1:{port}/_deploy"
    run = call_hook("post", "1.2.3", DEPLOY_HOOK_URL=url, DEPLOY_WEBHOOK_SECRET=SECRET)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "HTTP 202" in run.stdout
    assert (drop / "request").read_text() == "1.2.3\n"


@needs_curl
def test_call_hook_explains_a_refused_signature(listener):
    port, drop = listener()
    url = f"http://127.0.0.1:{port}/_deploy"
    run = call_hook("post", "1.2.3", DEPLOY_HOOK_URL=url, DEPLOY_WEBHOOK_SECRET="y" * 64)
    assert run.returncode == 1
    assert "refused the signature" in run.stdout
    assert not list(drop.iterdir())


@pytest.mark.parametrize("version", ["1.2", "1.2.3; id", "v1.2.3"])
def test_call_hook_wants_a_version(version):
    run = call_hook(
        "post", version, DEPLOY_WEBHOOK_SECRET=SECRET, DEPLOY_HOOK_URL="http://0.0.0.0:9/"
    )
    assert run.returncode == 2


@pytest.fixture
def healthz():
    """A stand-in for https://climpact.app/healthz whose version changes after N polls."""
    state = {"polls": 0, "switch_after": 2, "old": "0.1.1", "new": "0.1.2"}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["polls"] += 1
            live = state["new"] if state["polls"] > state["switch_after"] else state["old"]
            body = json.dumps({"status": "ok", "version": live, "core_version": "9.9.9"})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{server.server_address[1]}/healthz"
    yield state
    server.shutdown()
    server.server_close()


@needs_curl
def test_call_hook_waits_for_the_new_version(healthz):
    run = call_hook("wait", "0.1.2", HEALTHZ_URL=healthz["url"], DEPLOY_TIMEOUT="60")
    assert run.returncode == 0, run.stdout
    assert "runs 0.1.2" in run.stdout
    assert healthz["polls"] == 3


@needs_curl
def test_call_hook_fails_when_the_version_never_arrives(healthz):
    healthz["switch_after"] = 10**6
    run = call_hook("wait", "0.1.2", HEALTHZ_URL=healthz["url"], DEPLOY_TIMEOUT="0")
    assert run.returncode == 1
    assert "still reports 0.1.1" in run.stdout


# ---- update.sh, with stubbed docker and curl -----------------------------------------------

IMAGE = "ghcr.io/geoffwalmsley/climpact-web"

STUB_CURL = r"""#!/bin/sh
# curl -fsSL --retry 3 URL -o FILE: serve $STUB_RELEASES/<ref>/<file>, else 22 (HTTP 404).
url= out=
while [ "$#" -gt 0 ]; do
  case "$1" in -o) out="$2"; shift ;; https://*) url="$1" ;; esac
  shift
done
rest="${url#https://raw.githubusercontent.com/geoffwalmsley/climpactpy/}"
ref="${rest%%/*}"
file="${rest##*/}"
[ -f "$STUB_RELEASES/$ref/$file" ] || exit 22
cp "$STUB_RELEASES/$ref/$file" "$out"
"""

STUB_DOCKER = r"""#!/bin/sh
# Records each call; the "running" image is CLIMPACT_IMAGE in ./.env.
echo "docker $*" >>"$STUB_LOG"
image=$(sed -n 's/^CLIMPACT_IMAGE=//p' .env 2>/dev/null)
case "$1 $2" in
  "pull -q") case " ${STUB_BAD_PULL:-} " in *" $3 "*) exit 1 ;; esac ;;
  "compose run") case " ${STUB_BAD_MIGRATE:-} " in *" $image "*) exit 1 ;; esac ;;
  "compose up")
    if [ -n "${STUB_BLOCK:-}" ]; then
      while [ ! -e "$STUB_BLOCK" ]; do sleep 0.1; done
    fi ;;
  "compose exec")
    case " ${STUB_BROKEN:-} " in *" $image "*) exit 1 ;; esac
    echo "${image##*:}" ;;
  "image ls") printf '%s\n' ${STUB_IMAGES:-} ;;
esac
exit 0
"""


@pytest.fixture
def droplet(tmp_path):
    """/opt/climpact running 0.1.1, release files for v0.1.2 and v0.1.3, and stubs."""
    root = tmp_path / "climpact"
    root.mkdir()
    (root / ".env").write_text(f"POSTGRES_PASSWORD=x\nCLIMPACT_IMAGE={IMAGE}:0.1.1\nOTHER=1\n")
    for name in ("compose.yaml", ".env.example", "deploy-hook.py"):
        (root / name).write_text(f"{name} of 0.1.1\n")
    (root / "update.sh").write_text("update.sh of 0.1.1\n")
    (root / "hook").mkdir()
    releases = tmp_path / "releases"
    for tag in ("v0.1.2", "v0.1.3"):
        (releases / tag).mkdir(parents=True)
        for name in ("compose.yaml", ".env.example", "deploy-hook.py", "update.sh"):
            (releases / tag / name).write_text(f"{name} of {tag}\n")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    stubs = {"curl": STUB_CURL, "docker": STUB_DOCKER, "logger": "#!/bin/sh\nexit 0\n"}
    if not shutil.which("flock"):  # macOS: no util-linux; the lock test is skipped there
        stubs["flock"] = "#!/bin/sh\nexit 0\n"
    for name, text in stubs.items():
        (bin_ / name).write_text(text)
        (bin_ / name).chmod(0o755)
    log = tmp_path / "docker.log"
    log.touch()
    env = {
        "PATH": f"{bin_}:{os.environ['PATH']}",
        "CLIMPACT_DIR": str(root),
        "CLIMPACT_DEPLOY_USER": getpass.getuser(),
        "CLIMPACT_HEALTH_TIMEOUT": "0",
        "CLIMPACT_HEALTH_INTERVAL": "0",
        "STUB_RELEASES": str(releases),
        "STUB_LOG": str(log),
        "STUB_IMAGES": f"{IMAGE}:0.1.0 {IMAGE}:0.1.1 {IMAGE}:0.1.2 {IMAGE}:<none>",
        "HOME": str(tmp_path),
    }

    class Droplet:
        dir = root
        releases_dir = releases

        def run(self, *args, background=False, **extra):
            cmd = ["sh", str(DEPLOY / "update.sh"), *args]
            full = {**env, **extra}
            if background:
                return subprocess.Popen(
                    cmd, env=full, cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
                )
            return subprocess.run(
                cmd, env=full, cwd=tmp_path, capture_output=True, text=True, timeout=60
            )

        def image(self):
            for line in (root / ".env").read_text().splitlines():
                if line.startswith("CLIMPACT_IMAGE="):
                    return line.split("=", 1)[1]

        def calls(self):
            return log.read_text().splitlines()

    return Droplet()


def index(calls, prefix):
    return next(i for i, c in enumerate(calls) if c.startswith(prefix))


def test_update_deploys_a_release(droplet):
    run = droplet.run("0.1.2")
    assert run.returncode == 0, run.stderr
    assert droplet.image() == f"{IMAGE}:0.1.2"
    env = (droplet.dir / ".env").read_text()
    assert "POSTGRES_PASSWORD=x\n" in env and "OTHER=1\n" in env
    for name in ("compose.yaml", ".env.example", "deploy-hook.py", "update.sh"):
        assert (droplet.dir / name).read_text() == f"{name} of v0.1.2\n"
        assert (droplet.dir / ".previous" / name).read_text().endswith("of 0.1.1\n")
    assert os.access(droplet.dir / "update.sh", os.X_OK)
    assert (droplet.dir / ".previous" / "image").read_text() == f"{IMAGE}:0.1.1\n"
    calls = droplet.calls()
    # Pull, then migrate, then start, then check, in that order.
    order = [
        index(calls, f"docker pull -q {IMAGE}:0.1.2"),
        index(calls, "docker compose run --rm -T migrate"),
        index(calls, "docker compose up -d --wait"),
        index(calls, "docker compose restart deploy-hook"),  # its script changed
        index(calls, "docker compose exec -T web python"),
    ]
    assert order == sorted(order)
    # The new and the previous image are kept; older ones go.
    assert [c for c in calls if c.startswith("docker image rm")] == [
        f"docker image rm {IMAGE}:0.1.0"
    ]
    assert "deployed 0.1.2" in (droplet.dir / "deploy.log").read_text()
    assert not list(droplet.dir.glob(".staging.*"))


def test_update_accepts_a_tag_name(droplet):
    assert droplet.run("v0.1.2").returncode == 0
    assert droplet.image() == f"{IMAGE}:0.1.2"


def test_update_changes_nothing_when_the_pull_fails(droplet):
    run = droplet.run("0.1.2", STUB_BAD_PULL=f"{IMAGE}:0.1.2")
    assert run.returncode == 1
    assert "nothing changed" in run.stderr
    assert droplet.image() == f"{IMAGE}:0.1.1"
    assert (droplet.dir / "compose.yaml").read_text() == "compose.yaml of 0.1.1\n"
    assert not [c for c in droplet.calls() if c.startswith("docker compose")]


def test_update_changes_nothing_when_the_release_is_missing(droplet):
    run = droplet.run("0.2.0")
    assert run.returncode == 1
    assert droplet.image() == f"{IMAGE}:0.1.1"
    assert droplet.calls() == []


@pytest.mark.parametrize(
    "failure", ["STUB_BROKEN", "STUB_BAD_MIGRATE"], ids=["healthz fails", "migrate fails"]
)
def test_update_rolls_back_a_failed_deploy(droplet, failure):
    run = droplet.run("0.1.2", **{failure: f"{IMAGE}:0.1.2"})
    assert run.returncode == 1
    assert f"ROLLED BACK to {IMAGE}:0.1.1" in run.stderr
    assert droplet.image() == f"{IMAGE}:0.1.1"
    for name in ("compose.yaml", ".env.example", "deploy-hook.py", "update.sh"):
        assert (droplet.dir / name).read_text().endswith("of 0.1.1\n"), name
    calls = droplet.calls()
    ups = [c for c in calls if c.startswith("docker compose up")]
    assert len(ups) == (2 if failure == "STUB_BROKEN" else 1)
    # The rollback checked that the old version answers, and nothing was pruned.
    last_up = max(i for i, c in enumerate(calls) if c.startswith("docker compose up"))
    assert any(c.startswith("docker compose exec -T web") for c in calls[last_up:])
    assert not [c for c in calls if c.startswith("docker image rm")]
    assert "ROLLED BACK" in (droplet.dir / "deploy.log").read_text()


def test_update_reports_a_failed_rollback(droplet):
    run = droplet.run("0.1.2", STUB_BROKEN=f"{IMAGE}:0.1.2 {IMAGE}:0.1.1")
    assert run.returncode == 1
    assert "ROLLBACK to" in run.stderr and "FAILED TOO" in run.stderr


def test_update_keeps_hook_files_an_older_release_lacks(droplet):
    for name in ("deploy-hook.py", "update.sh"):
        (droplet.releases_dir / "v0.1.2" / name).unlink()
    run = droplet.run("0.1.2")
    assert run.returncode == 0, run.stderr
    assert (droplet.dir / "deploy-hook.py").read_text() == "deploy-hook.py of 0.1.1\n"
    assert (droplet.dir / "compose.yaml").read_text() == "compose.yaml of v0.1.2\n"
    assert not [c for c in droplet.calls() if "restart deploy-hook" in c]


@pytest.mark.parametrize(
    "arg", ["1.2", "1.2.3.4", "1.2.3rc1", "1.2.3;id", "", "١.٢.٣", "1.2.3\nid", "x1.2.3"]
)
def test_update_refuses_anything_but_a_version(droplet, arg):
    run = droplet.run(arg)
    assert run.returncode == 2
    assert droplet.calls() == []


def test_update_refuses_extra_arguments(droplet):
    assert droplet.run("0.1.2", "0.1.3").returncode == 2
    assert droplet.run("--hook", "0.1.2").returncode == 2


def test_update_runs_the_hooks_request(droplet):
    (droplet.dir / "hook" / "request").write_text("0.1.2\n")
    run = droplet.run("--hook")
    assert run.returncode == 0, run.stderr
    assert droplet.image() == f"{IMAGE}:0.1.2"
    assert not (droplet.dir / "hook" / "request").exists()


def test_update_checks_the_hooks_request_again(droplet):
    (droplet.dir / "hook" / "request").write_text("0.1.2; touch /tmp/x\n")
    run = droplet.run("--hook")
    assert run.returncode == 1
    assert "invalid version" in run.stderr
    assert not (droplet.dir / "hook" / "request").exists()
    assert droplet.calls() == []


def test_update_with_no_request_does_nothing(droplet):
    assert droplet.run("--hook").returncode == 0
    assert droplet.calls() == []


def test_update_install_hook_needs_root(droplet):
    if os.geteuid() == 0:
        pytest.skip("running as root")
    run = droplet.run("--install-hook")
    assert run.returncode == 1 and "needs root" in run.stderr


@pytest.mark.skipif(not shutil.which("flock"), reason="needs util-linux flock (Linux)")
def test_update_runs_one_deploy_at_a_time(droplet, tmp_path):
    release = tmp_path / "release-first"
    first = droplet.run("0.1.2", background=True, STUB_BLOCK=str(release))
    deadline = time.monotonic() + 20
    while not any(c.startswith("docker compose up") for c in droplet.calls()):
        assert time.monotonic() < deadline, "the first deploy never started"
        time.sleep(0.05)
    second = droplet.run("0.1.3", background=True)
    time.sleep(1.0)
    # The second is waiting for the lock: it has not even pulled its image.
    assert not any("0.1.3" in c for c in droplet.calls())
    assert second.poll() is None
    release.touch()
    out1, _ = first.communicate(timeout=30)
    out2, _ = second.communicate(timeout=30)
    assert first.returncode == 0, out1
    assert second.returncode == 0, out2
    assert b"another deploy is running" in out2
    calls = droplet.calls()
    assert index(calls, f"docker pull -q {IMAGE}:0.1.3") > index(calls, "docker compose exec")
    assert droplet.image() == f"{IMAGE}:0.1.3"
