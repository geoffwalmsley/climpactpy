"""Checks on the hosting files in deploy/ (#123)."""

import fnmatch
import re
from pathlib import Path

import pytest
from django.urls import URLPattern, URLResolver, get_resolver

DEPLOY = Path(__file__).resolve().parents[3] / "deploy"


def test_cloud_init_is_plain_ascii():
    """deploy/cloud-init.yaml is pasted into DigitalOcean's user-data box, and a paste that
    mangles one non-ASCII character (a clipboard without a UTF-8 locale turns "›" into
    "âº", with a C1 control byte) makes cloud-init reject the whole file and set up
    nothing. So the file holds printable ASCII, tabs and newlines only."""
    text = (DEPLOY / "cloud-init.yaml").read_bytes()
    bad = sorted(
        {
            (n, line.decode("utf-8", "replace").strip())
            for n, line in enumerate(text.splitlines(), 1)
            if any(b > 0x7E or (b < 0x20 and b != 0x09) for b in line)
        }
    )
    assert not bad, f"non-ASCII or control characters in cloud-init.yaml: {bad}"
    assert text.startswith(b"#cloud-config\n")


# ---- Cloudflare edge settings (#124) ---------------------------------------------------

CLOUDFLARE = DEPLOY / "cloudflare"
SAMPLE_UUID = "6f1c0d3e-6a7b-4c8d-9e0f-1a2b3c4d5e6f"
SAMPLES = {"uuid": SAMPLE_UUID, "str": "su_ANN", "slug": "station-data", "path": "plots/a.png"}

# The URLs that start a job or take an upload: the paths the one rate-limiting rule of
# Cloudflare's free plan counts. That rule can match only the path, not the method, so it
# must leave out the htmx polls (`.../progress`) and the htmx POSTs sent as a form is
# filled in (`.../validate`, `w/<id>/batch/options`, `gridded/<id>/checks`).
RATE_LIMITED = {
    "stations:new",
    "stations:sample",
    "stations:setup",
    "stations:qc_continue",
    "stations:recalculate",
    "stations:sector",
    "batch:start",
    "batch:sample",
    "batch:add_files",
    "batch:run",
    "jobs:retry",
    "gridded:upload",
    "gridded:sample",
}


def cloudflare_rule(name: str):
    """The expression in deploy/cloudflare/<name>.txt as a function of the path (and the
    method, GET unless given). Handles the subset of Cloudflare's rules language the files
    use: `wildcard` (whole value, case-insensitive, `*` matches anything including `/`),
    `contains`, `eq` (exact), the path and method fields, `and`, `or`, `not` and
    parentheses."""
    text = (CLOUDFLARE / f"{name}.txt").read_text()
    field = r"http\.request\.uri\.path"
    code = re.sub(field + r' wildcard ("[^"]*")', r"_wildcard(path, \1)", text)
    code = re.sub(field + r' contains ("[^"]*")', r"(\1 in path)", code)
    code = re.sub(field + r' eq ("[^"]*")', r"(path == \1)", code)
    code = re.sub(r'http\.request\.method eq ("[^"]*")', r"(method == \1)", code)
    assert "http." not in code, f"{name}.txt uses a field or operator the test can't read"

    def wildcard(path, pattern):
        return fnmatch.fnmatchcase(path.lower(), pattern.lower())

    compiled = compile(f"({code})", name, "eval")
    return lambda path, method="GET": eval(
        compiled, {"__builtins__": {}, "_wildcard": wildcard, "path": path, "method": method}
    )


def app_paths() -> dict[str, str]:
    """Every URL pattern of the app, as a sample path, by its `namespace:name`."""

    def fill(route: str) -> str:
        return re.sub(r"<(\w+):\w+>", lambda m: SAMPLES[m.group(1)], route)

    out = {}

    def walk(patterns, prefix, namespace):
        for p in patterns:
            route = prefix + fill(str(p.pattern))
            if isinstance(p, URLResolver):
                walk(p.url_patterns, route, p.namespace or namespace)
            elif isinstance(p, URLPattern) and p.name:
                out[f"{namespace}:{p.name}" if namespace else p.name] = "/" + route

    walk(get_resolver().url_patterns, "", None)
    return out


def test_cloudflare_files_are_plain_ascii():
    """They are pasted into the dashboard's expression editor, like cloud-init.yaml."""
    for path in CLOUDFLARE.glob("*.txt"):
        text = path.read_bytes()
        assert all(b == 0x0A or 0x20 <= b <= 0x7E for b in text), path.name


def test_rate_limit_counts_only_job_starting_paths():
    paths = app_paths()
    assert len(paths) > 40
    rule = cloudflare_rule("rate-limit")
    counted = {name for name, path in paths.items() if rule(path)}
    assert counted == RATE_LIMITED
    # The Inputs panel's sheets start jobs when applied (#198, #199); their progress does not.
    base = f"/w/{SAMPLE_UUID}/sydney/inputs/"
    for key in ("file", "station", "base-period", "thresholds", "settings"):
        assert rule(base + key), key
    assert not rule(base + "progress")
    assert not rule(paths["stations:qc_progress"])
    assert not rule(paths["stations:validate"])
    assert not rule(paths["jobs:file"])


def test_waf_rules_leave_the_app_alone():
    paths = app_paths()
    block, challenge = cloudflare_rule("waf-block"), cloudflare_rule("waf-challenge")
    assert not [name for name, path in paths.items() if block(path)]
    assert [name for name, path in paths.items() if challenge(path)] == ["core:patterns"]
    for probe in ["/wp-login.php", "/.env", "/.git/config", "/xmlrpc.php", "/cgi-bin/x"]:
        assert block(probe), probe
    assert not block("/.well-known/security.txt")
    assert challenge("/admin/") and challenge("/administrator")


def test_cache_rules_split_static_from_everything_else():
    static, bypass = cloudflare_rule("cache-static"), cloudflare_rule("cache-bypass")
    assert static("/static/climpact_web/css/climpact.36cde401c4f6.css")
    assert not bypass("/static/climpact_web/css/climpact.36cde401c4f6.css")
    for path in app_paths().values():
        assert bypass(path) and not static(path), path


def test_deploy_settings_fit_cloudflare():
    """HSTS for a year from the first deploy, and an upload limit under the free plan's
    100 MB request bodies, in both .env.example and the compose.yaml defaults."""
    env = (DEPLOY / ".env.example").read_text()
    compose = (DEPLOY / "compose.yaml").read_text()
    assert re.search(r"^CLIMPACT_WEB_HSTS_SECONDS=31536000$", env, re.M)
    assert "${CLIMPACT_WEB_HSTS_SECONDS:-31536000}" in compose
    upload = int(re.search(r"^CLIMPACT_WEB_MAX_UPLOAD_MB=(\d+)$", env, re.M).group(1))
    default = int(re.search(r"CLIMPACT_WEB_MAX_UPLOAD_MB:-(\d+)\}", compose).group(1))
    assert upload <= 100 and default <= 100


ABUSE_SETTINGS = [
    "CLIMPACT_WEB_TURNSTILE_SITE_KEY",
    "CLIMPACT_WEB_TURNSTILE_SECRET_KEY",
    "CLIMPACT_WEB_MAX_ACTIVE_JOBS_PER_IP",
    "CLIMPACT_WEB_MAX_DAILY_JOBS_PER_IP",
    "CLIMPACT_WEB_MAX_QUEUED_JOBS",
    "CLIMPACT_WEB_MIN_FREE_DISK_GB",
    "CLIMPACT_WEB_JOB_TIME_LIMIT_MINUTES",
]


def test_abuse_limit_settings_reach_the_app():
    """#125: every limit is in .env.example (Turnstile keys empty) and passed to the app by
    compose.yaml, and web alone of the app's services can reach Cloudflare's siteverify."""
    env = (DEPLOY / ".env.example").read_text()
    compose = (DEPLOY / "compose.yaml").read_text()
    for name in ABUSE_SETTINGS:
        assert re.search(rf"^{name}=", env, re.M), name
        assert f"{name}: ${{{name}:-" in compose, name
    assert re.search(r"^CLIMPACT_WEB_TURNSTILE_SECRET_KEY=$", env, re.M)
    services = compose.split("\nservices:\n", 1)[1].split("\nnetworks:\n", 1)[0]
    blocks = dict(re.findall(r"^  (\w+):\n(.*?)(?=^  \w+:\n|\Z)", services, re.M | re.S))
    assert "networks: [backend, egress]" in blocks["web"]
    for name in ("worker", "migrate", "purge", "db"):
        assert "egress" not in blocks[name], name


def test_csp_report_only_switch_reaches_the_app():
    """#137: the Content Security Policy's report-only switch is in .env.example, off, and
    compose.yaml passes it to the app (enforced when .env leaves it out)."""
    env = (DEPLOY / ".env.example").read_text()
    compose = (DEPLOY / "compose.yaml").read_text()
    assert re.search(r"^CLIMPACT_WEB_CSP_REPORT_ONLY=false$", env, re.M)
    assert "CLIMPACT_WEB_CSP_REPORT_ONLY: ${CLIMPACT_WEB_CSP_REPORT_ONLY:-false}" in compose


# ---- Deploy on release (#126) ----------------------------------------------------------


def compose_services() -> dict[str, str]:
    compose = (DEPLOY / "compose.yaml").read_text()
    services = compose.split("\nservices:\n", 1)[1].split("\nnetworks:\n", 1)[0]
    return dict(re.findall(r"^  ([\w-]+):\n(.*?)(?=^  [\w-]+:\n|\Z)", services, re.M | re.S))


def test_cloudflare_lets_the_deploy_call_through():
    """The workflow's POST to /_deploy is matched by no blocking, challenging or rate
    limiting rule, and the skip rule matches that request and nothing the app serves."""
    skip = cloudflare_rule("waf-skip-deploy")
    assert skip("/_deploy", "POST")
    assert not skip("/_deploy", "GET") and not skip("/_deploy/", "POST")
    for name, path in app_paths().items():
        for method in ("GET", "POST"):
            assert not skip(path, method), name
    for rule in ("waf-block", "waf-challenge", "rate-limit", "cache-static"):
        assert not cloudflare_rule(rule)("/_deploy", "POST"), rule
    assert cloudflare_rule("cache-bypass")("/_deploy")
    assert "_deploy" not in " ".join(app_paths().values())


def test_deploy_hook_service_is_locked_down():
    blocks = compose_services()
    hook = blocks["deploy-hook"]
    assert "networks: [backend]" in hook  # no route out
    assert "read_only: true" in hook and "cap_drop: [ALL]" in hook
    assert 'user: "10001:10001"' in hook
    assert "DEPLOY_WEBHOOK_SECRET: ${DEPLOY_WEBHOOK_SECRET:-}" in hook
    compose = (DEPLOY / "compose.yaml").read_text()
    assert "docker.sock" not in compose and "ports:" not in compose
    # The secret reaches the hook only.
    assert compose.count("DEPLOY_WEBHOOK_SECRET") == 2
    # The same Python image as the app's Dockerfile, so the two are updated together.
    dockerfile = (DEPLOY.parent / "Dockerfile").read_text()
    python = re.search(r"^ARG PYTHON_IMAGE=(\S+)$", dockerfile, re.M).group(1)
    assert f"image: {python}" in hook
    assert re.search(r"^DEPLOY_WEBHOOK_SECRET=$", (DEPLOY / ".env.example").read_text(), re.M)


def test_worker_has_time_to_hand_back_its_job():
    worker = compose_services()["worker"]
    seconds = int(re.search(r"stop_grace_period: (\d+)s", worker).group(1))
    assert seconds >= 120


def test_release_deploys_only_final_releases():
    yaml = pytest.importorskip("yaml")  # PyYAML comes with xclim

    workflow = yaml.safe_load((DEPLOY.parent / ".github/workflows/release.yml").read_text())
    jobs = workflow["jobs"]
    deploy = jobs["deploy"]
    assert set(deploy["needs"]) == {"version", "publish"}
    condition = " ".join(deploy["if"].split())
    for part in (
        "github.event_name == 'release'",
        "!github.event.release.prerelease",
        "needs.version.outputs.prerelease == 'false'",
        "needs.publish.result == 'success'",
    ):
        assert part in condition
    assert deploy["environment"]["name"] == "production"
    assert deploy["permissions"] == {"contents": "read"}
    # Nothing else depends on it: it is the last job.
    assert not [name for name, job in jobs.items() if "deploy" in (job.get("needs") or [])]
    # Only releases (and dry runs of this file on pull requests) start the workflow.
    triggers = workflow.get("on") or workflow.get(True)
    assert set(triggers) == {"release", "pull_request"}
    steps = " ".join(str(step.get("run", "")) for step in deploy["steps"])
    assert "call-hook.sh post" in steps and "call-hook.sh wait" in steps


def test_uptime_check_reaches_healthz():
    """DigitalOcean's Uptime check (#127) probes https://climpact.app/healthz from its own
    cloud addresses: no rule may block, challenge, rate-limit or cache it, and the skip
    rule (waf-skip-healthz.txt) matches GET and HEAD /healthz and nothing else."""
    healthz = app_paths()["core:healthz"]
    assert healthz == "/healthz"
    skip = cloudflare_rule("waf-skip-healthz")
    assert skip(healthz, "GET") and skip(healthz, "HEAD")
    assert not skip(healthz, "POST") and not skip("/healthz/", "GET")
    for name, path in app_paths().items():
        if name != "core:healthz":
            assert not skip(path) and not skip(path, "HEAD"), name
    assert not skip("/_deploy", "POST") and not cloudflare_rule("waf-skip-deploy")(healthz)
    for rule in ("waf-block", "waf-challenge", "rate-limit", "cache-static"):
        for method in ("GET", "HEAD"):
            assert not cloudflare_rule(rule)(healthz, method), rule
    assert cloudflare_rule("cache-bypass")(healthz)
