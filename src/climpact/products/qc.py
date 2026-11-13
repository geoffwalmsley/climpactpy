"""Quality-control output tables.

Every QC file is declared once, in :data:`QC_REPORTS`: its name, the check that builds
its table (:mod:`climpact.qc`) and the layout R writes it with. :func:`qc_reports`
registers them all as one product. ``qc/nastatistics`` is separate: R computes it from
the climdex input object, not from the QC rows.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from climpact import qc
from climpact.config import QCParams
from climpact.io.climpact_csv import NA_TOKEN, format_r_number
from climpact.io.output_files import FileFormat, with_file_format
from climpact.outputs import product, register
from climpact.station import StationRun


@dataclass(frozen=True)
class QCReport:
    """One QC file: ``qc/<name>``."""

    name: str
    # (QC rows, thresholds) -> table with R's columns.
    check: Callable[[pd.DataFrame, QCParams], pd.DataFrame]
    # Thresholds -> the file's Description line.
    description: Callable[[QCParams], str]
    # Quoted line written when nothing is found; None: R writes none.
    empty_message: str | None = None
    # R writes the column names with write.table(quote = TRUE).
    quote_header: bool = False

    def table(self, rows: pd.DataFrame, params: QCParams) -> pd.DataFrame:
        """The check's table with the file format attached.

        A check whose table has a categorical ``Section`` column (``outliers``) is
        written in sections: the column gives the section titles, empty ones included.
        """
        table = self.check(rows, params)
        sections = None
        if SECTION in table.columns:
            counts = table[SECTION].value_counts(sort=False)
            sections = tuple((str(title), int(counts[title])) for title in counts.index)
            table = table.drop(columns=SECTION)
        # The checks use write.table(sep = ",", quote = FALSE): missing values are "NA".
        return with_file_format(
            table,
            FileFormat(
                description=self.description(params),
                sep=",",
                na=NA_TOKEN,
                quote_header=self.quote_header,
                empty_message=self.empty_message,
                sections=sections,
            ),
        )


# Column of a check's table naming the section each row is written in.
SECTION = "Section"


n = format_r_number

# In the order allqc runs them. outliers (fourboxes) is written in sections. tmaxmin and
# humongous test length(data.frame) == 0, which counts columns, so their "NO ... FOUND"
# line is never written. flatline_tn's description says TX.
QC_REPORTS: list[QCReport] = [
    QCReport(
        "outliers",
        qc.outliers,
        lambda p: (
            f"Outliers shown in *boxes.png. IQR thresholds of {n(p.iqr_prec)} and "
            f"{n(p.iqr_temp)} were used for precipitation and temperature variables, "
            "respectively."
        ),
    ),
    QCReport(
        "tmaxmin",
        lambda rows, p: qc.tmax_le_tmin(rows),
        lambda p: "Dates where TN>TX",
    ),
    QCReport(
        "toolarge",
        qc.too_large,
        lambda p: (
            f"Dates where precipitation > {n(p.prec_max)} mm or abs(temperature) > "
            f"{n(p.temp_max)} degrees."
        ),
    ),
    QCReport(
        "duplicates",
        lambda rows, p: qc.duplicate_dates(rows),
        lambda p: "Dates that have been used more than once in your input file.",
        empty_message="NO DUPLICATE DATES FOUND",
    ),
    QCReport(
        "tx_jumps",
        lambda rows, p: qc.jumps(rows, "tmax", p),
        lambda p: f"Dates where the change in TX is > {n(p.jump)} degrees.",
        empty_message="NO LARGE TX JUMPS FOUND",
    ),
    QCReport(
        "tn_jumps",
        lambda rows, p: qc.jumps(rows, "tmin", p),
        lambda p: f"Dates where the change in TN is > {n(p.jump)} degrees.",
        empty_message="NO LARGE TN JUMPS FOUND",
    ),
    QCReport(
        "tx_flatline",
        lambda rows, p: qc.flatline(rows, "tmax", p),
        lambda p: f"Dates where TX values have been repeated more than {p.flatline_days} times.",
        empty_message="NO REPEATED TX FOUND",
        quote_header=True,
    ),
    QCReport(
        "tn_flatline",
        lambda rows, p: qc.flatline(rows, "tmin", p),
        lambda p: f"Dates where TX values have been repeated more than {p.flatline_days} times.",
        empty_message="NO REPEATED TN FOUND",
        quote_header=True,
    ),
]


@product
def qc_reports(run: StationRun) -> dict[str, pd.DataFrame]:
    """Every file in :data:`QC_REPORTS`."""
    rows = run.rows
    return {f"qc/{report.name}": report.table(rows, run.qc) for report in QC_REPORTS}


@register("qc/nastatistics")
def na_statistics(run: StationRun) -> pd.DataFrame:
    """Missing days per year for each variable (R ``write.NA.statistics``)."""
    ds = run.data
    missing = ds[["pr", "tasmax", "tasmin"]].isnull().groupby("time.year").sum()
    return pd.DataFrame(
        {
            "Year": missing["year"].to_numpy().astype(float),
            "Prec": missing["pr"].to_numpy().astype(float),
            "TX": missing["tasmax"].to_numpy().astype(float),
            "TN": missing["tasmin"].to_numpy().astype(float),
        }
    )
