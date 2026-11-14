"""The PDF report of a station run (``climpact.report``)."""

import re
import zipfile
from pathlib import Path

import pytest

from climpact.batch import BatchStation, run_batch, run_station
from climpact.cli import main
from climpact.config import IndexParams, QCParams, StationMetadata
from climpact.io.climpact_csv import read_climpact_csv
from climpact.report import _Index, _trend_rows, index_key, qc_summary, report_file, write_report
from tests.parity.catalogue import REFERENCE_DIR
from tests.test_batch import write_station

pytest.importorskip("matplotlib")

PARAMS = IndexParams(custom=None)
SYDNEY = REFERENCE_DIR / "sydney" / "sydney_observatory_hill_1936-2015"


def pdf_pages(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page\b(?!s)", pdf))


def check_xref(pdf: bytes) -> dict[int, int]:
    """Every object the cross-reference table lists starts where it says."""
    start = int(re.findall(rb"startxref\s+(\d+)", pdf)[-1])
    head = re.match(rb"xref\n0 (\d+)\n", pdf[start:])
    assert head, "no xref table at startxref"
    offsets = {}
    table = pdf[start + head.end() :]
    for number in range(int(head.group(1))):
        entry = table[number * 20 : number * 20 + 20]
        offset, kind = int(entry[:10]), entry[17:18]
        if kind == b"n":
            assert pdf[offset:].startswith(b"%d 0 obj" % number), number
            offsets[number] = offset
    return offsets


@pytest.fixture
def run(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    station_file = write_station(data / "stn.txt")
    out = tmp_path / "out"
    events = []
    written, _ = run_station(
        station_file,
        StationMetadata("stn", latitude=-10, longitude=20, base_start=2000, base_end=2001),
        PARAMS,
        out,
        progress=lambda *e: events.append(e[0]),
        zip=True,
        report=True,
    )
    return out, written, events


def test_run_station_writes_the_report_beside_the_station_folder(run):
    out, written, events = run
    assert written["report"] == out / "stn_report.pdf" == report_file(out, "stn")
    assert events[-2:] == ["report", "zip"]
    with zipfile.ZipFile(written["zip"]) as z:
        assert not [n for n in z.namelist() if "report" in n]  # the zip keeps R's layout


def test_report_pages_bookmarks_links_and_metadata(run):
    out, written, _ = run
    pdf = written["report"].read_bytes()
    assert pdf.startswith(b"%PDF")
    check_xref(pdf)
    # Two years of data: the indices with values are plotted, the others listed.
    plotted = len(set(re.findall(rb"/Title \(([^)]+)\)", pdf)))
    assert pdf_pages(pdf) > 10
    assert b"/Outlines" in pdf and b"/PageMode /UseOutlines" in pdf
    assert b"/Lang (en)" in pdf and b"/DisplayDocTitle true" in pdf
    assert b"(stn: Climpact report)" in pdf
    links = re.findall(rb"/Subtype /Link", pdf)
    assert len(links) >= 4  # the contents
    assert re.search(rb"/Dest \[ \d+ 0 R /Fit \]", pdf)
    assert plotted > 4  # bookmarks: cover, contents, QC, indices and each index
    # The last catalogue, which the xref points to, has the outline.
    root = int(re.findall(rb"/Root (\d+) 0 R", pdf)[-1])
    offset = check_xref(pdf)[root]
    assert b"/Outlines" in pdf[offset : pdf.index(b"endobj", offset)]


def test_report_needs_the_station_outputs(tmp_path):
    with pytest.raises(FileNotFoundError):
        write_report(tmp_path, StationMetadata("none"), PARAMS)


def test_report_to_a_given_path_with_progress(run, tmp_path):
    out, _, _ = run
    stages = []
    target = tmp_path / "elsewhere" / "r.pdf"
    path = write_report(
        out, StationMetadata("stn"), PARAMS, target, progress=stages.append, title="My title"
    )
    assert path == target and target.is_file() and stages == ["report"]
    assert not target.with_name("r.pdf.part").exists()


def test_index_key():
    assert index_key("day_of_txx_MON") == "txx"
    assert index_key("3month_spi_MON") == "3month_spi"
    assert index_key("TX90-HWN_ANN") == "TX90-HWN"
    assert index_key("tx95t_DAY") == "tx95t"
    assert index_key("TNgt0_ANN") == "TNgt0"


def test_qc_summary_from_r_files():
    """Counts of R's own QC files for Sydney."""
    summary = qc_summary(SYDNEY, SYDNEY.name, QCParams())
    counts = {check: rows for check, _what, rows in summary.checks}
    assert counts["Repeated dates"] == 0
    assert counts["TX at or below TN"] == 1
    assert counts["Values too large"] == 4
    assert counts["TX jumps"] == 4
    assert counts["Outliers"] > 300
    assert (summary.first_year, summary.last_year) == (1936, 2015)
    nastats = read_climpact_csv(SYDNEY / "qc" / f"{SYDNEY.name}_nastatistics.csv").data
    assert summary.totals == tuple(int(nastats[c].sum()) for c in ("Prec", "TX", "TN"))
    assert all(any(v) for _y, *v in summary.missing)
    assert "200 mm" in dict((c, w) for c, w, _ in summary.checks)["Values too large"]


def test_qc_summary_without_files(tmp_path):
    summary = qc_summary(tmp_path, "x", QCParams(jump=15))
    assert {rows for _c, _w, rows in summary.checks} == {None}
    assert summary.totals is None
    assert "15 °C" in dict((c, w) for c, w, _ in summary.checks)["TX jumps"]


def test_trend_rows_add_the_seasons_of_the_trend_file():
    from climpact.plots import index_plots
    from climpact.report import _FolderTables

    tables = _FolderTables(SYDNEY, SYDNEY.name)  # R's own index files
    plots = [p for _, g in index_plots(tables, IndexParams()) for p in g]
    txx = _Index("txx", [p for p in plots if index_key(p.name) == "txx"])
    trend = read_climpact_csv(SYDNEY / "trend" / f"{SYDNEY.name}_trend.csv").data
    rows = _trend_rows(txx, trend)
    assert [r.label.split()[0] for r in rows] == ["Yearly", "Monthly", "DJF", "MAM", "JJA", "SON"]
    assert rows[0].p_value is not None and rows[2].p_value is None
    djf = trend[(trend["Index"] == "txx") & (trend["Frequency"] == "DJF")].iloc[0]
    assert rows[2].slope == djf["Slope"] and rows[2].years == "1936-2015"
    assert rows[0].unit == "°C per year" and rows[1].unit == "°C per month"
    assert rows[2].significant == (djf["Lower bound"] > 0 or djf["Upper bound"] < 0)
    # No trend: tx95t.
    tx95t = _Index("tx95t", [p for p in plots if p.name == "tx95t_DAY"])
    assert _trend_rows(tx95t, trend) == []


def test_batch_reports_outside_the_batch_folder(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    write_station(data / "a.txt")
    station = BatchStation("a.txt", -10, 20, PARAMS, 2)
    out, reports = tmp_path / "batch", tmp_path / "reports"
    [result] = run_batch([station], data, out, 2000, 2001, workers=1, zip=True, report_dir=reports)
    assert result.ok
    assert (reports / "a_report.pdf").is_file()
    with zipfile.ZipFile(tmp_path / "batch.zip") as z:
        assert not [n for n in z.namelist() if "report" in n]


def test_cli_report(tmp_path, capsys):
    data = tmp_path / "data"
    data.mkdir()
    station_file = write_station(data / "stn.txt")
    out = tmp_path / "out"
    args = ["run", str(station_file), "--out", str(out), "--no-custom", "--report"]
    assert main([*args, "--base-start", "2000", "--base-end", "2001"]) == 0
    assert (out / "stn_report.pdf").is_file()
    assert f"Wrote the report to {out / 'stn_report.pdf'}" in capsys.readouterr().out


def test_cli_batch_report(tmp_path, capsys):
    data = tmp_path / "data"
    data.mkdir()
    write_station(data / "a.txt")
    meta = tmp_path / "meta.txt"
    meta.write_text(
        "station_file latitude longitude wsdin csdin Tb_HDD Tb_CDD Tb_GDD rxnday rnnmm txtn "
        "SPEI\na.txt -10 20 1 1 18 18 10 3 30 2 24\n"
    )
    out = tmp_path / "b"
    args = ["batch", str(meta), str(data), "--out", str(out), "--report", "--workers", "1"]
    assert main([*args, "--base-start", "2000", "--base-end", "2001"]) == 0
    assert (tmp_path / "b_reports" / "a_report.pdf").is_file()
    assert "Wrote the stations' reports to" in capsys.readouterr().out


def test_report_path_helper():
    assert report_file("out", "stn") == Path("out") / "stn_report.pdf"
