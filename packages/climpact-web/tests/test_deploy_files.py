"""Checks on the hosting files in deploy/ (#123)."""

import fnmatch
import re
from pathlib import Path

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
# filled in (`.../validate`, `batch/<id>/options`, `gridded/<id>/checks`).
RATE_LIMITED = {
    "stations:upload",
    "stations:sample",
    "stations:load",
    "stations:replace_file",
    "stations:qc_run",
    "stations:qc_replace",
    "stations:qc_continue",
    "stations:indices",
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
    """The expression in deploy/cloudflare/<name>.txt as a function of the path. Handles
    the subset of Cloudflare's rules language the files use: `wildcard` (whole value,
    case-insensitive, `*` matches anything including `/`), `contains`, `and`, `or`,
    `not` and parentheses."""
    text = (CLOUDFLARE / f"{name}.txt").read_text()
    field = r"http\.request\.uri\.path"
    code = re.sub(field + r' wildcard ("[^"]*")', r"_wildcard(path, \1)", text)
    code = re.sub(field + r' contains ("[^"]*")', r"(\1 in path)", code)
    assert "http." not in code, f"{name}.txt uses a field or operator the test can't read"

    def wildcard(path, pattern):
        return fnmatch.fnmatchcase(path.lower(), pattern.lower())

    compiled = compile(f"({code})", name, "eval")
    return lambda path: eval(compiled, {"__builtins__": {}, "_wildcard": wildcard, "path": path})


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
