"""Make the synthetic QC stress station (run ``qc_stress`` in stations.csv).

None of the real reference stations has a duplicated date, and several QC checks fire
at only a few of them. This script takes Potsdam (``input/potsdam_1961-2020.txt``) and
plants faults for every per-value QC check, including the threshold edges and R's
quirks, writing ``input/qc_stress_1961-2020.txt``. Only its ``qc/`` files are compared
with R; its index files are not part of the parity catalogue.

    uv run python reference/make_qc_stress.py

The output is deterministic. Planted faults (default QC thresholds):

- duplicate dates: an identical repeat, a repeat with other values, a date given three
  times, a repeat that is out of order in the file, and a repeat that is all missing
  (the last row of a date is what the indices use);
- a missing day (row removed) and a row with an invalid date (dropped by R);
- TN > TX, TN == TX, and TN > TX with missing precipitation;
- values exactly at and just beyond the too-large limits (200 mm, -0.1 mm, |T| 50),
  one next to a missing value;
- TX and TN jumps exactly at 20, just below, two equal jumps in a row, a jump next to a
  missing value, and two-decimal values whose rounded change depends on R's ``round``;
- flat runs of 5 and 6 equal values (only 6 is reported), a long flat run, and a flat
  run broken by a missing value.
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).parent
SOURCE = HERE / "input" / "potsdam_1961-2020.txt"
TARGET = HERE / "input" / "qc_stress_1961-2020.txt"
NA = "-99.9"

Row = list[str]  # year, month, day, prcp, tmax, tmin as text


def key(y: int, m: int, d: int) -> tuple[str, str, str]:
    return (str(y), str(m), str(d))


def main() -> None:
    rows: list[Row] = [line.split("\t") for line in SOURCE.read_text().splitlines()]
    index = {tuple(r[:3]): i for i, r in enumerate(rows)}

    def at(y: int, m: int, d: int) -> Row:
        return rows[index[key(y, m, d)]]

    def put(y: int, m: int, d: int, prcp: str | None = None, tx=None, tn=None) -> None:
        r = at(y, m, d)
        for col, value in ((3, prcp), (4, tx), (5, tn)):
            if value is not None:
                r[col] = value

    def series(y: int, m: int, d: int, column: int, values: list[str]) -> None:
        start = index[key(y, m, d)]
        for offset, value in enumerate(values):
            rows[start + offset][column] = value

    # TN >= TX (tmaxmin lists TN == TX too).
    put(1962, 4, 10, tx="8.2", tn="9.5")
    put(1962, 4, 11, tx="7.4", tn="7.4")
    put(1962, 4, 12, prcp=NA, tx="6.1", tn="6.3")

    # Too large: 200 and +-50 are not flagged, anything beyond is; negative rain is.
    put(1963, 7, 1, prcp="200")
    put(1963, 7, 2, prcp="200.1")
    put(1963, 7, 3, prcp="-0.1")
    put(1963, 7, 4, tx="50")
    put(1963, 7, 5, tx="50.1")
    put(1963, 12, 1, tn="-50")
    put(1963, 12, 2, tn="-50.1")
    put(1963, 12, 3, prcp=NA, tx="-55.2", tn=NA)
    put(1963, 12, 4, prcp="350.5", tx=NA, tn=NA)

    # TX jumps (abs(round(diff, 1)) >= 20, reported on the first day with the change).
    series(1966, 5, 1, 4, ["10", "30", "15", "15.1"])  # +20 flagged, -15 not
    series(1966, 5, 10, 4, ["10", "29.9", "20"])  # +19.9 not flagged
    series(1966, 5, 20, 4, ["0", "20", "40", "25"])  # two +20 in a row: one run, reported once
    series(1966, 6, 1, 4, ["5", NA, "30", "10"])  # NA breaks; -20 after it flagged
    series(1966, 6, 10, 4, ["10.1", "30.05", "30.05"])  # change 19.95: R rounds to 19.9
    series(1966, 6, 20, 4, ["10.05", "30.1", "30.1"])  # change 20.05: R rounds to 20
    # TN jumps (reported with the TN value of the first day).
    series(1967, 1, 5, 5, ["-2", "-27.5", "-3"])  # -25.5 then +24.5
    series(1967, 1, 15, 5, ["-5", "-24.9", "-10"])  # 19.9: not flagged
    series(1967, 2, 1, 5, ["1.25", "21.3", "21.3"])  # 20.05 -> R rounds to 20, flagged

    # Flat lines: 5 equal values (4 zero changes) are not reported, 6 are.
    series(1968, 3, 1, 4, ["11.1"] * 5 + ["13"])
    series(1968, 3, 10, 4, ["12.2"] * 6 + ["14"])
    series(1968, 4, 1, 5, ["0"] * 12 + ["2"])
    series(1968, 5, 1, 5, ["7.7"] * 4 + [NA] + ["7.7"] * 4 + ["9"])  # broken by NA
    series(1968, 6, 1, 4, ["20.01", "20.04", "20", "19.98", "20.03", "20.02", "22"])  # round to 0
    series(1968, 7, 1, 5, ["15"] * 7 + ["16"])

    # A missing day, and NA values scattered through.
    del_key = key(1970, 8, 15)
    for y, m, d in [(1971, 2, 3), (1985, 10, 10), (2001, 1, 1)]:
        put(y, m, d, prcp=NA, tx=NA, tn=NA)
    put(1975, 9, 9, tx=NA)
    put(1976, 9, 9, tn=NA)

    # Duplicate dates: inserted after the original row unless stated.
    inserts: list[tuple[tuple[str, str, str], Row]] = []
    for y, m, d in [(1965, 3, 10)]:  # identical repeat
        inserts.append((key(y, m, d), list(at(y, m, d))))
    inserts.append((key(1972, 6, 15), ["1972", "6", "15", "0", "33.3", "18.8"]))  # other values
    inserts.append((key(1980, 1, 20), ["1980", "1", "20", "1.1", "2.2", "-1.1"]))  # three times
    inserts.append((key(1980, 1, 20), ["1980", "1", "20", "0.4", "3.3", "-2.2"]))
    # Out of order: 3 May repeated after 10 May, with TN > TX.
    inserts.append((key(1990, 5, 10), ["1990", "5", "3", "4.4", "10.5", "12.5"]))
    inserts.append((key(1995, 7, 1), ["1995", "7", "1", NA, NA, NA]))  # repeat all missing
    # A row with an invalid date (dropped by R's create_user_data_ts).
    inserts.append((key(1999, 2, 28), ["1999", "2", "30", "0", "5", "1"]))

    out: list[Row] = []
    for r in rows:
        if tuple(r[:3]) == del_key:
            continue
        out.append(r)
        out.extend(new for after, new in inserts if after == tuple(r[:3]))
    TARGET.write_text("".join("\t".join(r) + "\n" for r in out))
    print(f"wrote {TARGET.relative_to(HERE.parent)}: {len(out)} rows")


if __name__ == "__main__":
    main()
