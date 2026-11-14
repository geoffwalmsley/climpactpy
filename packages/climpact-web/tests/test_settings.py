"""Settings for the local and hosted modes, read from the environment."""

import importlib.util
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

import climpact_web

SETTINGS_FILE = Path(climpact_web.__file__).parent / "settings.py"

HOSTED = {
    "CLIMPACT_WEB_MODE": "hosted",
    "CLIMPACT_WEB_SECRET_KEY": "x" * 50,
    "CLIMPACT_WEB_ALLOWED_HOSTS": "climpact.example.org, www.climpact.example.org",
    "DATABASE_URL": "postgres://climpact:pw@db.example.org:5432/climpact",
    "CLIMPACT_WEB_STATIC_ROOT": "/srv/climpact-web/static",
}


@pytest.fixture
def load_settings(monkeypatch, tmp_path):
    """Run settings.py afresh, as a separate module, under the given environment."""

    def load(**env):
        for name in [*HOSTED, "CLIMPACT_WEB_DATA_DIR", "CLIMPACT_WEB_DEBUG"]:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("CLIMPACT_WEB_DATA_DIR", str(tmp_path / "data"))
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        spec = importlib.util.spec_from_file_location("settings_under_test", SETTINGS_FILE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return load


def test_local_defaults(load_settings, tmp_path):
    s = load_settings()
    data = tmp_path / "data"
    assert s.MODE == "local" and not s.IS_HOSTED
    assert s.DEBUG is False
    assert s.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"
    assert s.DATABASES["default"]["NAME"] == data / "db.sqlite3"
    assert s.MEDIA_ROOT == data / "media"
    assert s.RUNS_DIR == data / "media" / "runs"
    assert s.ALLOWED_HOSTS == ["localhost", "127.0.0.1", "[::1]"]
    assert s.WHITENOISE_USE_FINDERS is True
    # Static files collected into the data folder by `climpact-web` (#82)
    assert s.STATIC_ROOT == data / "static"
    assert s.STORAGES["staticfiles"]["BACKEND"].endswith("storage.LocalStaticFilesStorage")
    assert s.SECRET_KEY
    assert not getattr(s, "SESSION_COOKIE_SECURE", False)
    # Reading the settings creates nothing
    assert not data.exists()


def test_local_reads_secret_key_file(load_settings, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "secret_key").write_text("from-the-file\n")
    assert load_settings().SECRET_KEY == "from-the-file"


def test_hosted(load_settings):
    s = load_settings(**HOSTED)
    assert s.IS_HOSTED
    db = s.DATABASES["default"]
    assert db["ENGINE"] == "django.db.backends.postgresql"
    assert (db["HOST"], db["PORT"], db["NAME"], db["USER"]) == (
        "db.example.org",
        5432,
        "climpact",
        "climpact",
    )
    assert s.ALLOWED_HOSTS == ["climpact.example.org", "www.climpact.example.org"]
    assert s.SESSION_COOKIE_SECURE and s.CSRF_COOKIE_SECURE and s.SECURE_SSL_REDIRECT
    assert s.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")
    assert s.STORAGES["staticfiles"]["BACKEND"] == "climpact_web.core.storage.StaticFilesStorage"


@pytest.mark.parametrize(
    "missing",
    [
        "CLIMPACT_WEB_SECRET_KEY",
        "CLIMPACT_WEB_ALLOWED_HOSTS",
        "DATABASE_URL",
        "CLIMPACT_WEB_STATIC_ROOT",
    ],
)
def test_hosted_requires(load_settings, missing):
    env = {k: v for k, v in HOSTED.items() if k != missing}
    with pytest.raises(ImproperlyConfigured, match=missing):
        load_settings(**env)


def test_bad_values(load_settings):
    with pytest.raises(ImproperlyConfigured, match="CLIMPACT_WEB_MODE"):
        load_settings(CLIMPACT_WEB_MODE="cloud")
    with pytest.raises(ImproperlyConfigured, match="CLIMPACT_WEB_DEBUG"):
        load_settings(CLIMPACT_WEB_DEBUG="maybe")


def test_upload_limit_setting(load_settings):
    s = load_settings(CLIMPACT_WEB_MAX_UPLOAD_MB="3")
    assert s.MAX_UPLOAD_BYTES == 3 * 1024 * 1024


def test_pattern_library_setting(load_settings):
    assert load_settings().PATTERN_LIBRARY is False
    assert load_settings(CLIMPACT_WEB_DEBUG="true").PATTERN_LIBRARY is True
    assert load_settings(CLIMPACT_WEB_PATTERN_LIBRARY="true").PATTERN_LIBRARY is True
