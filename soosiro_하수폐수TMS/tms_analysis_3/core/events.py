# -*- coding: utf-8 -*-
"""
하천 자료만으로 '강우 유출 사건일'을 정의(기상자료가 없어도 쓰기 위함, v2 24번 방법을 일반화)
- 측정소 사건: 탁도 ≥ 31일 이동중앙값×TURB_RATIO  또는  전기전도도 ≤ 이동중앙값×EC_RATIO(빗물 희석)
- 광역 사건일: 같은 수계에서 자료가 있는 측정소 중 REGIONAL_SHARE 이상이 사건
- 건기 기준일: 앞뒤 3일 안에 측정소 사건이 없는 날
"""
from __future__ import annotations

import pandas as pd

TURB_RATIO = 3.0
EC_RATIO = 0.80
REGIONAL_SHARE = 0.25
MIN_ST = 4


def _ratio(s, win=31):
    return s / s.rolling(win, center=True, min_periods=10).median()


def station_events(df):
    """df: io.load_daily() 결과 → [basin, station, date, ev_turb, ev_ec, event, wet, dry]"""
    out = []
    for (b, st), g in df.groupby(["basin", "station"]):
        g = g.set_index("date").sort_index()
        g = g[~g.index.duplicated()].asfreq("D")
        f = pd.DataFrame(index=g.index)
        f["ev_turb"] = (_ratio(g["Turb"]) >= TURB_RATIO) if "Turb" in g else False
        f["ev_ec"] = (_ratio(g["EC"]) <= EC_RATIO) if "EC" in g else False
        f["ok"] = (g["Turb"].notna() if "Turb" in g else False) | (g["EC"].notna() if "EC" in g else False)
        ev = (f["ev_turb"] | f["ev_ec"]).astype(bool)
        f["event"] = ev
        f["wet"] = ev | ev.shift(1, fill_value=False)
        near = ev.copy()
        for k in range(1, 4):
            near = near | ev.shift(k, fill_value=False) | ev.shift(-k, fill_value=False)
        f["dry"] = ~near & f["ok"]
        f["basin"], f["station"] = b, st
        out.append(f.reset_index())
    return pd.concat(out, ignore_index=True)


def regional_events(sev):
    """수계별 광역 사건일 [basin, date, share, n, regional]"""
    ok = sev[sev["ok"]]
    r = ok.groupby(["basin", "date"]).agg(share=("event", "mean"), n=("event", "size")).reset_index()
    r["regional"] = (r["share"] >= REGIONAL_SHARE) & (r["n"] >= MIN_ST)
    return r
