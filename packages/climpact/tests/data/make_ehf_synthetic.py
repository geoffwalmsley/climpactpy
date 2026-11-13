"""Write tests/data/ehf_synthetic.txt, the synthetic station for tests/test_ehf.py.

TAVG follows a small seasonal cycle (below 19 degC), with 60 days at exactly 25 degC in the
2002 base year, so that the base-period T95 is exactly 25, and hot days at 40 degC that
make the EHF heatwaves listed below. TX and TN are TAVG + 5 and TAVG - 5.

    .venv/bin/python packages/climpact/tests/data/make_ehf_synthetic.py
"""

import datetime as dt
import math
from pathlib import Path

start, end = dt.date(2001, 1, 1), dt.date(2007, 12, 31)
HOT = 40.0
hot = []  # inclusive date ranges set to HOT


def rng(a, b):
    hot.append((dt.date.fromisoformat(a), dt.date.fromisoformat(b)))


rng("2001-03-10", "2001-03-12")  # 2001: first year, always missing
rng("2002-03-10", "2002-03-12")  # single heatwave
rng("2002-04-01", "2002-04-03")
rng("2002-04-06", "2002-04-08")  # 2 days apart: joined
rng("2002-04-20", "2002-04-22")
rng("2002-04-26", "2002-04-28")  # 3 days apart: separate
rng("2002-05-08", "2002-05-10")  # 7 May missing: two missing lead days
rng("2003-12-30", "2004-01-02")  # crosses 31 December: split
rng("2004-12-10", "2004-12-12")  # missing days in its 30-day window
rng("2005-01-01", "2005-01-02")  # first positive day 1 Jan: 2004 gets the lead days only
rng("2007-03-10", "2007-03-12")  # 2007: masked (4 days missing in June)
missing = {dt.date(2002, 5, 7), dt.date(2004, 11, 20), dt.date(2004, 11, 21), dt.date(2004, 11, 22)}
missing |= {dt.date(2007, 6, d) for d in (1, 2, 3, 4)}
lines = []
d, i = start, 0
while d <= end:
    doy = d.timetuple().tm_yday
    t = round(15 + 3 * math.cos(2 * math.pi * (doy - 15) / 365) + ((i * 37) % 11 - 5) / 10, 1)
    if d.year == 2002 and (d.month == 8 or (d.month == 9 and d.day <= 29)):
        t = 25.0  # base-period days at 25 degC fix T95 at exactly 25
    if any(a <= d <= b for a, b in hot):
        t = HOT
    if d in missing:
        tx = tn = -99.9
    else:
        tx, tn = round(t + 5, 1), round(t - 5, 1)
    lines.append(f"{d.year}\t{d.month}\t{d.day}\t0.0\t{tx:.1f}\t{tn:.1f}")
    d += dt.timedelta(days=1)
    i += 1
open(Path(__file__).with_name("ehf_synthetic.txt"), "w").write("\n".join(lines) + "\n")
