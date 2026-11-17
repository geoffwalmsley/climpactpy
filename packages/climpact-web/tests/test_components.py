"""The design system's components, landing page and pattern library (#71): every
component renders, the accessibility hooks are in the markup, and the pages work before
the screens they link to exist."""

import re
from pathlib import Path

import pytest
from django import forms
from django.core.management import call_command
from django.template.loader import render_to_string
from django.test import override_settings
from django.urls import include, path

import climpact_web
from climpact_web.core import navigation
from climpact_web.core.forms import PatternDemoForm
from climpact_web.core.views import pattern_context

PACKAGE = Path(climpact_web.__file__).parent
COMPONENTS = PACKAGE / "core" / "templates" / "components"
SPRITE = PACKAGE / "core" / "static" / "climpact_web" / "icons" / "icons.svg"

pytestmark = pytest.mark.django_db


def render(name, **context):
    return render_to_string(f"components/{name}.html", context).strip()


def bound_form():
    form = PatternDemoForm(data={"latitude": "-133", "base_start": "1990", "base_end": "1961"})
    form.is_valid()
    return form


# ---- Every component -------------------------------------------------------------------


def test_every_component_is_in_the_pattern_library():
    """The pattern library is the review surface, so it must show every component."""
    source = (PACKAGE / "core" / "templates" / "core" / "patterns.html").read_text()
    source += (PACKAGE / "core" / "templates" / "base.html").read_text()
    used_by_others = {"field_errors", "messages", "toasts", "theme_toggle", "skeleton", "badge"}
    used_by_others.add("spark")  # in the theme headline
    for component in COMPONENTS.glob("*.html"):
        name = component.stem
        assert f'"components/{name}.html"' in source or name in used_by_others, name


def test_every_component_documents_its_parameters():
    for component in COMPONENTS.glob("*.html"):
        source = component.read_text()
        assert "{% comment %}" in source or "{#" in source, component.name


def test_icons_used_exist_in_the_sprite():
    symbols = set(re.findall(r'<symbol id="([\w-]+)"', SPRITE.read_text()))
    sources = "".join(p.read_text() for p in (PACKAGE / "core" / "templates").rglob("*.html"))
    used = set(re.findall(r'\{% icon "([\w-]+)"', sources))
    used |= set(re.findall(r'icon="([\w-]+)"', sources))
    used |= {d.icon for d in navigation.DESTINATIONS}
    used |= set(pattern_context(bound_form())["icons"])
    assert used <= symbols, used - symbols


def test_icon_tag_decorative_and_labelled():
    html = render_to_string("components/badge.html", {"label": "Passed", "icon": "check"})
    assert 'aria-hidden="true"' in html and "icons.svg#check" in html
    from climpact_web.core.templatetags.ui import icon

    labelled = icon("warning", "Warning")
    assert 'role="img"' in labelled and 'aria-label="Warning"' in labelled


def test_button_variants():
    html = render("button", label="Go", variant="secondary", size="lg", icon="upload")
    assert html.startswith('<button type="button"')
    assert "button--secondary" in html and "button--lg" in html and "<span>Go</span>" in html
    link = render("button", label="Go", href="/next/")
    assert link.startswith('<a href="/next/"') and link.endswith("</a>")
    assert "disabled" in render("button", label="Go", href="/x/", disabled=True)
    icon_only = render("button", label="Refresh", icon="refresh", icon_only=True)
    assert '<span class="sr-only">Refresh</span>' in icon_only
    assert 'aria-busy="true"' in render("button", label="Go", busy=True)
    assert "button--block" in render("button", label="Go", full_width=True)


def test_button_is_not_full_width_inside_a_template_block():
    """Django's {{ block }} variable must not leak into the button's parameters."""
    html = render_to_string("core/home.html", {"ways": [], "steps": []})
    assert "button--block" not in html


def test_field_inline_errors_are_linked_to_the_input():
    form = bound_form()
    html = render("field", field=form["latitude"], unit="°N")
    assert 'aria-invalid="true"' in html
    assert 'id="id_latitude_error"' in html and 'id="id_latitude_helptext"' in html
    assert 'aria-describedby="id_latitude_helptext id_latitude_error"' in html
    assert 'for="id_latitude"' in html and "input-group__unit" in html
    assert "field--error" in html


def test_field_optional_checkbox_and_radio():
    form = bound_form()
    assert "(optional)" in render("field", field=form["notes"])
    checkbox = render("field", field=form["detrend"])
    assert 'class="check"' in checkbox and 'type="checkbox"' in checkbox
    radios = render("field", field=form["method"])
    assert radios.strip().startswith("<fieldset") and "<legend>" in radios
    assert radios.count('type="radio"') == 2


def test_form_error_summary_links_to_fields():
    html = render("form_errors", form=bound_form())
    assert 'role="alert"' in html and 'href="#id_latitude"' in html
    assert render("form_errors", form=PatternDemoForm()).strip() == ""


def test_dropzone_is_a_real_file_input():
    """Without JavaScript the drop zone is a labelled, visible file input."""
    html = render("dropzone", field=bound_form()["station_file"], hint="Up to 50 MB")
    assert 'type="file"' in html and 'for="id_station_file"' in html
    assert "data-dropzone" in html and "Up to 50 MB" in html
    assert 'id="id_station_file_error"' in html


@pytest.mark.parametrize("kind", ["info", "success", "warning", "error"])
def test_alert_kinds(kind):
    html = render("alert", kind=kind, title="Title", message="Message")
    assert f"alert--{kind}" in html and "<h2" in html and "Message" in html
    assert 'role="' not in html  # alerts present at page load are not live regions
    assert 'role="alert"' in render("alert", kind=kind, message="m", live="assertive")


def test_card_link_and_muted():
    html = render("card", title="Batch", text="Many stations", href="/batch/", icon="layers")
    assert "card--link" in html and 'href="/batch/"' in html and "<h3" in html
    muted = render("card", title="Gridded", muted=True, badge_label="Soon", level=2)
    assert "card--muted" in muted and "<h2" in muted and "badge" in muted


def test_table_numeric_columns_and_empty():
    columns = [{"label": "Year"}, {"label": "TXx", "numeric": True}]
    html = render("table", caption="Indices", columns=columns, rows=[["2011", "41.2"]])
    assert 'role="region"' in html and 'tabindex="0"' in html and "<caption>" in html
    assert '<th scope="row">2011</th>' in html and '<td class="num">41.2</td>' in html
    empty = render("table", caption="Indices", columns=columns, rows=[], empty="Nothing")
    assert 'colspan="2"' in empty and "Nothing" in empty


def test_tabs_work_as_links_without_js():
    tabs = [{"id": "a", "label": "Annual", "text": "x"}, {"id": "b", "label": "Monthly"}]
    html = render("tabs", label="Views", tabs=tabs)
    assert 'href="#a"' in html and 'id="a"' in html and "data-tabs" in html
    assert 'role="tab' not in html  # ui.js adds the ARIA roles


def test_progress_determinate_and_indeterminate():
    html = render("progress", id="p", label="Indices", value=45, note="Thresholds")
    assert 'value="45"' in html and 'aria-labelledby="p-label"' in html and "45%" in html
    assert 'aria-live="polite"' in html
    indeterminate = render("progress", id="p", label="Waiting", value=None)
    assert "value=" not in indeterminate.replace('max="100"', "")


def test_stages_states():
    stages = [{"label": "QC", "state": "done"}, {"label": "Indices", "state": "current"}]
    html = render("stages", label="Stages", stages=stages)
    assert "stages__item--done" in html and 'aria-current="step"' in html
    assert "(done)" in html and "(in progress)" in html


def test_skeleton_empty_state_disclosure_dialog_chart():
    skeleton = render("skeleton", lines=2)
    assert skeleton.count("skeleton__line") == 2 and 'aria-busy="true"' in skeleton
    assert render("skeleton").count("skeleton__line") == 3
    assert "skeleton__block" in render("skeleton", chart_block=True, height="8rem", lines=0)
    empty = render("empty_state", title="No runs", action_label="Start", action_href="/s/")
    assert "No runs" in empty and 'href="/s/"' in empty
    assert "<details" in render("disclosure", summary="Why?", text="Because")
    dialog = render("dialog", id="d", title="Delete?", text="Sure?", confirm_label="Delete")
    assert '<dialog class="dialog" id="d" aria-labelledby="d-title">' in dialog
    assert 'method="dialog"' in dialog
    chart = render("chart_frame", id="c", title="TXx", summary="Rising", csv_href="/c.csv")
    assert "data-chart-plot" in chart and 'href="/c.csv"' in chart and "Rising" in chart


def test_theme_toggle_hidden_without_js():
    html = render("theme_toggle")
    assert "data-theme-toggle hidden" in html and html.count("aria-pressed") == 3


# ---- Step indicator --------------------------------------------------------------------


def test_flow_steps_states():
    steps = navigation.batch_steps("check", urls={"upload": "/u/", "check": "/c/"})
    assert [s.state for s in steps] == ["complete", "current", "upcoming"]
    assert [s.url for s in steps] == ["/u/", None, None]
    assert [s.number for s in steps] == [1, 2, 3]
    assert [s.key for s in navigation.gridded_steps("files")] == ["files", "setup", "results"]
    with pytest.raises(ValueError):
        navigation.batch_steps("nope")
    # The single station has no steps since #179: its sections are tabs.
    assert not hasattr(navigation, "station_steps")


def test_count_filter_groups_thousands():
    """#115: every count is shown the same way, with the thousands grouped."""
    from climpact_web.core.templatetags.ui import count

    assert count(29220) == "29,220" and count(7) == "7" and count("1234") == "1,234"
    assert count(1234.0) == "1,234" and count(2.5) == 2.5 and count("n/a") == "n/a"
    assert count(None) is None


def test_steps_component():
    html = render("steps", steps=navigation.batch_steps("check", urls={"upload": "/u/"}))
    assert '<a class="steps__link" href="/u/">' in html
    assert 'aria-current="step"' in html and "Step 2 of 3:" in html
    assert "Optional" not in html


# ---- Landing page and navigation -------------------------------------------------------


def test_landing_page(client):
    html = client.get("/").content.decode()
    assert "<h1" in html and "indices of climate extremes" in html
    # Step 1 exists (#76): start is a link, the sample a one-click POST form
    assert re.search(r'<a href="/station/new"[^>]*>.*?Start with your data', html, re.S)
    assert re.search(
        r'<form method="post" action="/station/sample">.*?csrfmiddlewaretoken.*?'
        r'<button type="submit".*?Try with sample data',
        html,
        re.S,
    )
    assert "Available soon" not in html  # every other way to run Climpact exists now
    # "How it works" is a short paragraph, not the steps again (#173).
    how = re.search(r'aria-labelledby="how-title">.*?</section>', html, re.S).group(0)
    assert "<h3" not in how and "<li" not in how
    assert re.search(r'<a [^>]*href="/gridded/"', html)  # gridded (#85), local mode
    assert re.search(r'<a [^>]*href="/batch/"', html)  # batch exists (#80)
    for title in ("Batch", "Gridded", "Help", "Command line"):
        assert title in html
    assert "/static/climpact_web/js/ui.js" in html
    # One stylesheet carries both themes (#118): data-theme on <html> picks one.
    assert "/static/climpact_web/css/climpact.css" in html and "theme-dark" not in html
    nav = re.findall(r'<nav class="site-nav".*?</nav>', html, re.S)[0]
    # The app shell (#227): Workspaces (the calculations until #242) and Gridded.
    assert re.findall(r'href="([^"]+)"', nav) == ["/jobs/", "/gridded/"]
    # Help is at the end of the header since #197, leading to the help or the page's guide.
    assert re.search(r'<a class="site-header__link" id="app-help" href="/help/"', html)
    # Below 600px a <details> menu (no JavaScript) holds the same links (#115), and Index
    # reference from the end of the header (#227).
    menu = re.search(r'<details class="site-menu">.*?</details>', html, re.S).group(0)
    assert re.search(r"<summary[^>]*>.*Menu.*</summary>", menu, re.S)
    assert re.findall(r'<a href="([^"]+)"', menu) == [
        *re.findall(r'href="([^"]+)"', nav),
        "/help/indices/#the-indices",
    ]
    assert 'aria-label="Main"' in menu


@override_settings(IS_HOSTED=True, GRIDDED_ENABLED=False)
def test_landing_page_hosted_hides_gridded(client):
    html = client.get("/").content.decode()
    assert "Gridded" not in html and "install Climpact on your own computer" in html


def stub(name):
    from django.http import HttpResponse

    return path(f"{name}/", lambda request: HttpResponse(name), name=name)


urlpatterns = [
    path("station/", include("climpact_web.stations.urls")),
    path("batch/", include("climpact_web.batch.urls")),
    path("help/", include(([stub("index")], "help"))),
    path("jobs/", include("climpact_web.jobs.urls")),
    path("", include("climpact_web.core.urls")),
]


@override_settings(ROOT_URLCONF=__name__)
def test_destinations_link_once_their_urls_exist(client):
    html = client.get("/").content.decode()
    assert 'href="/help/index/"' in html
    page = client.get("/help/index/")
    assert page.status_code == 200
    items = navigation.nav_items(page.wsgi_request)
    # Help is the header's Help button since #197, not a link among the destinations.
    # The header is Workspaces and Gridded since #227 (gridded is off here).
    assert [i["label"] for i in items] == ["Workspaces"]
    help_button = navigation.page_help(page.wsgi_request)
    assert help_button == {"url": "/help/index/", "title": None, "current": True}


# ---- Pattern library -------------------------------------------------------------------


def test_pattern_library_off_by_default(client, settings):
    assert settings.PATTERN_LIBRARY is False
    assert client.get("/patterns/").status_code == 404


@override_settings(PATTERN_LIBRARY=True)
def test_pattern_library(client):
    response = client.get("/patterns/")
    assert response.status_code == 200
    html = response.content.decode()
    for section in ("colour", "buttons", "forms", "dropzone", "alerts", "overlays", "cards"):
        assert f'id="{section}"' in html
    for section in ("tables", "tabs", "steps", "progress", "loading", "help", "charts"):
        assert f'id="{section}"' in html
    assert 'aria-invalid="true"' in html and "data-error-summary" in html
    assert not re.search(r'(src|href)="(https?:)?//', html)  # nothing from the network


def test_design_snapshots(tmp_path):
    out = tmp_path / "review"
    call_command("design_snapshots", str(out))
    jobs = ("job-running", "job-finished", "jobs")
    stations = ("new", "new-problems", "setup", "setup-errors", "qc")
    names = ("index", "patterns", "404", *jobs, *(f"station-{n}" for n in stations))
    for name in names:
        for suffix in ("", "-dark"):
            html = (out / f"{name}{suffix}.html").read_text()
            assert 'href="static/climpact_web/css/climpact.css"' in html
            assert '"/static/' not in html
            assert "icons.svg#" not in html and '<symbol id="upload"' in html
    assert 'data-theme="dark"' in (out / "index-dark.html").read_text()
    assert "Step 9 of 14" in (out / "job-running.html").read_text()
    assert "Download all results (zip, 7.1\xa0MB)" in (out / "job-finished.html").read_text()
    assert "Line 3 has 5 values" in (out / "station-new-problems.html").read_text()
    assert "Read: 1936–2015, 29,220 days" in (out / "station-setup.html").read_text()
    assert "has no data: the file covers" in (out / "station-setup-errors.html").read_text()
    assert (out / "static" / "climpact_web" / "css" / "climpact.css").is_file()
    assert (out / "static" / "climpact_web" / "js" / "ui.js").is_file()


def test_demo_form_validation():
    form = bound_form()
    assert set(form.errors) >= {"latitude", "base_end", "station_file", "station_name"}
    assert isinstance(form.fields["method"].widget, forms.RadioSelect)
