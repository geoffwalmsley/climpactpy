"""Write the synthetic stations for the outlier (``fourboxes``) tests in tests/test_qc.py.

    uv run python packages/climpact/tests/data/make_fourboxes_synthetic.py

``fourboxes_edges.txt`` (2001-2003) has cases none of the reference runs has:

- February: TX missing throughout, so neither TX nor DTR has a February box;
- March: no rain at all, so precipitation has no March box;
- April: TX values on and just beyond the TX fences (3 interquartile ranges), placed
  from the rounded fence, so the comparison with the hinges' floating-point arithmetic
  decides; the April TX values come from a small set, so the hinges are tied and do not
  move when the edge values are placed;
- May: TN is 10 on every day but two (interquartile range 0), so both others are outliers;
- June: a day with TX but no TN (DTR missing) and a day with no precipitation value;
- a few very wet days.

``fourboxes_dry.txt`` (15 March to 10 October 2001): no rain and no TN, so the file
has only the TX sections; the months outside the record have no box.

``tests/data/r_fourboxes.R`` runs R's ``fourboxes`` on both.
"""

import datetime as dt
import math
import random
from pathlib import Path

HERE = Path(__file__).parent
NA = None


def fivenum(x):
    x = sorted(x)
    n = len(x)
    n4 = math.floor((n + 3) / 2) / 2
    d = [1, n4, (n + 1) / 2, n + 1 - n4, n]
    return [0.5 * (x[math.floor(i) - 1] + x[math.ceil(i) - 1]) for i in d]


def days(start, end):
    d = start
    while d <= end:
        yield d
        d += dt.timedelta(days=1)


def fmt(v):
    return "-99.9" if v is None else f"{v:.1f}"


def write(name, rows):
    path = HERE / name
    path.write_text(
        "".join(f"{d.year}\t{d.month}\t{d.day}\t" + "\t".join(map(fmt, r)) + "\n" for d, *r in rows)
    )
    print(f"wrote {path.name}: {len(rows)} rows")


def edges():
    r = random.Random(26)
    rows = []
    for d in days(dt.date(2001, 1, 1), dt.date(2003, 12, 31)):
        season = 6 * math.sin(2 * math.pi * (d.timetuple().tm_yday - 100) / 365)
        tx = round(20 + season + r.uniform(-3, 3), 1)
        tn = round(tx - r.uniform(4, 12), 1)
        pr = round(r.expovariate(1 / 4), 1) if r.random() < 0.3 else 0.0
        if d.month == 2:
            tx = NA
        if d.month == 3:
            pr = 0.0
        if d.month == 4:
            tx = r.choice([19.0, 19.5, 20.0, 20.3, 20.5, 21.1, 21.5, 22.0])
        if d.month == 5:
            tn = 10.0
        rows.append([d, pr, tx, tn])
    at = {row[0]: row for row in rows}

    def put(date, col, value):
        at[dt.date.fromisoformat(date)][col] = value

    # April TX on and beyond its fences (coefficient 3).
    april = [row[2] for row in rows if row[0].month == 4]
    s = fivenum(april)
    iqr = s[3] - s[1]
    up, low = round(s[3] + 3 * iqr, 1), round(s[1] - 3 * iqr, 1)
    put("2001-04-10", 2, up)
    put("2002-04-10", 2, round(up + 0.1, 1))
    put("2001-04-20", 2, low)
    put("2002-04-20", 2, round(low - 0.1, 1))
    put("2003-04-20", 2, round(low - 0.1, 1))
    moved = fivenum([row[2] for row in rows if row[0].month == 4])
    assert moved[1::2] == s[1::2], "April hinges moved"
    print(f"April TX hinges {s[1]!r}, {s[3]!r}; fences {s[3] + 3 * iqr!r}, {s[1] - 3 * iqr!r}")
    # May TN: interquartile range 0.
    put("2002-05-05", 3, 10.1)
    put("2003-05-06", 3, 9.9)
    # June: DTR missing, precipitation missing.
    put("2001-06-03", 3, NA)
    put("2001-06-04", 1, NA)
    # Very wet days.
    put("2001-01-15", 1, 150.0)
    put("2003-07-02", 1, 95.5)
    put("2003-07-03", 1, 120.2)
    write("fourboxes_edges.txt", rows)


def dry():
    r = random.Random(126)
    rows = []
    for d in days(dt.date(2001, 3, 15), dt.date(2001, 10, 10)):
        tx = round(22 + r.uniform(-4, 4), 1)
        rows.append([d, 0.0, tx, NA])
    rows[40][2] = 45.0
    rows[100][2] = -3.0
    write("fourboxes_dry.txt", rows)


if __name__ == "__main__":
    edges()
    dry()
