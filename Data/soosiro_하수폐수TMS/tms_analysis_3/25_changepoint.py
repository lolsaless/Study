# -*- coding: utf-8 -*-
"""
25. 변화점(계단형 수준 변화) — 계절 제거 주간 중앙값에 PELT, 같은 날 여러 항목이 함께 바뀐 '측정소 이벤트'(점검·교체 후보)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import config as C
from core import Report, io, st

REQUIRES = ["river_daily"]
LEVEL = "중급"
VARS = ["WT", "pH", "EC", "DO", "Turb", "TOC", "TN", "TP", "Chl_a"]
MIN_SHIFT = {"pH": 0.2, "DO": 0.8, "WT": 1.0}     # 비로그 항목 최소 변화폭. 로그 항목은 20%


def segments(y, pen):
    try:
        import ruptures as rpt
        return rpt.Pelt(model="l2", min_size=8).fit(y.reshape(-1, 1)).predict(pen=pen)[:-1]
    except ImportError:          # 간이: 이분 탐색 CUSUM 1회
        n = len(y)
        best, k = 0, None
        for i in range(6, n - 6):
            gain = i * (n - i) / n * (y[:i].mean() - y[i:].mean()) ** 2
            if gain > best:
                best, k = gain, i
        return [k] if k and best > pen else []


def main():
    rep = Report("25_changepoint", "25. 변화점: 수준이 계단처럼 바뀐 시점", level=LEVEL,
                 purpose="계절을 뺀 뒤에도 남는 '계단'은 센서 교체·보정, 공사·준설, 상류 배출원 변화의 흔적이다. "
                         "같은 측정소에서 여러 항목이 같은 주에 바뀌면 장비 점검을 먼저 의심한다.")
    d = io.load_daily(VARS)
    rep.data_info(d)
    rows = []
    for b, stn, v, s in io.iter_series(d, VARS):
        x = st.to_log(s, v)
        # 계절 제거: 같은 측정소의 '같은 달 중앙값'(전 연도 합산)을 뺀다 → 계절은 빠지고 계단은 남는다
        clim = x.groupby(x.index.month).transform("median")
        wk = (x - clim).resample("W").median().dropna()
        if len(wk) < 40:
            continue
        y = wk.values
        sd = y.std()                     # 전체 표준편차로 표준화(자기상관 있는 주 자료에서 과검출 방지)
        cps = segments((y - y.mean()) / (sd or 1), pen=4 * np.log(len(y)))   # 보수적 벌점(후보만 남김)
        edges = [0] + list(cps) + [len(y)]
        for i, k in enumerate(cps):
            before, after = y[edges[i]:k], y[k:edges[i + 2]]
            diff = np.median(after) - np.median(before)
            big = (abs(np.exp(diff) - 1) >= 0.2) if v in C.LOG_VARS else abs(diff) >= MIN_SHIFT.get(v, 0)
            if big:
                rows.append({"basin": b, "station": stn, "var": v, "시점(주)": wk.index[k],
                             "변화": (np.exp(diff) - 1) * 100 if v in C.LOG_VARS else diff,
                             "단위": "%" if v in C.LOG_VARS else C.VAR_INFO[v][1],
                             "앞구간(주)": len(before), "뒤구간(주)": len(after)})
    t = pd.DataFrame(rows)
    if t.empty:
        rep.p("유의한 계단 변화가 없다.")
        return rep.save()
    rep.csv(t, "changepoints.csv")
    rep.h("1. 항목별 변화점 수")
    rep.table(t.groupby("var").size().rename("변화점").reindex(VARS).dropna().reset_index())
    rep.h("2. 한 측정소에서 같은 시기(±2주) 3개 이상 항목이 바뀐 경우 — 장비 점검·교체 후보")
    t = t.sort_values(["station", "시점(주)"])
    multi = []
    for stn, g in t.groupby("station"):
        for ts in g["시점(주)"].unique():
            near = g[(g["시점(주)"] - ts).abs() <= pd.Timedelta(weeks=2)]
            if near["var"].nunique() >= 3:
                multi.append({"station": stn, "basin": g["basin"].iloc[0], "시점": ts, "항목": ", ".join(sorted(near["var"].unique())),
                              "항목수": near["var"].nunique()})
    mt = pd.DataFrame(multi).drop_duplicates(["station", "항목"]) if multi else pd.DataFrame()
    rep.table(mt)
    rep.finding(f"계단형 변화 {len(t)}건(측정소 {t['station'].nunique()}곳). 여러 항목이 동시에 바뀐 '측정소 이벤트' {len(mt)}건 — 자료 확정 전 장비 이력과 대조 필요")
    rep.h("3. 변화폭 큰 순")
    big = t.assign(abs_=t["변화"].abs()).sort_values("abs_", ascending=False).drop(columns="abs_")
    rep.table(big.head(25))
    rep.save()


if __name__ == "__main__":
    main()
