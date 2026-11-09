# -*- coding: utf-8 -*-
"""
35. 극값(POT–GPD) — 상위 5% 초과분 일반화 파레토 적합(사건 단위 묶기), 꼬리 두께 ξ, 1년·2년 재현 농도
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats

import config as C
from core import Report, io

REQUIRES = ["river_daily"]
LEVEL = "심화"
VARS = ["Turb", "TP", "TOC", "Chl_a", "TN", "EC"]
Q_THR = 0.95
RUN = 3      # 3일 안에 이어진 초과는 한 사건


def decluster(s, u):
    ex = s[s > u]
    if ex.empty:
        return ex
    grp = (ex.index.to_series().diff() > pd.Timedelta(days=RUN)).cumsum()
    return ex.groupby(grp.values).max()


def main():
    rep = Report("35_extreme_value", "35. 극값: 꼬리 두께와 재현 농도", level=LEVEL,
                 purpose="고농도 사건이 '가끔 크게' 오는 측정소(꼬리가 두꺼움)와 '고만고만'한 측정소를 구분하고, 1년·2년에 한 번 올 만한 농도를 추정한다.")
    d = io.load_daily(VARS)
    rep.data_info(d)
    years = (d["date"].max() - d["date"].min()).days / 365.25
    rep.p(f"⚠ 자료 기간 {years:.1f}년 — 2년 재현값은 외삽에 가깝다. 측정소 간 '순위·꼬리 비교' 위주로 쓴다.")
    rows = []
    for b, stn, v, s in io.iter_series(d, VARS):
        x = s.dropna()
        u = x.quantile(Q_THR)
        pk = decluster(x, u)
        if len(pk) < 10:
            continue
        exc = (np.log(pk) - np.log(u)) if v != "EC" else (pk - u)
        try:
            xi, _, sigma = stats.genpareto.fit(exc.values, floc=0)
        except Exception:  # noqa: BLE001
            continue
        lam = len(pk) / (len(x) / 365.25)            # 연간 사건 수
        rl = {}
        for T in [1, 2]:
            m = lam * T
            q = u * np.exp(stats.genpareto.ppf(1 - 1 / m, xi, 0, sigma)) if (m > 1 and v != "EC") else (
                u + stats.genpareto.ppf(1 - 1 / m, xi, 0, sigma) if m > 1 else np.nan)
            rl[f"{T}년 재현"] = q
        rows.append({"basin": b, "station": stn, "var": v, "임계(p95)": u, "사건 수": len(pk), "연간 사건": lam,
                     "ξ(꼬리)": xi, "σ": sigma, **rl, "관측 최대": x.max(), "최대/중앙": x.max() / x.median()})
    t = pd.DataFrame(rows)
    t = t[(t["ξ(꼬리)"].abs() < 1.5)]            # 불안정 적합 제외
    rep.csv(t, "gpd_by_station.csv")
    rep.h("1. 항목별 꼬리 두께(로그 초과분 기준 ξ)")
    rep.table(t.groupby("var").agg(측정소=("station", "size"), ξ중앙=("ξ(꼬리)", "median"),
                                   두꺼운꼬리=("ξ(꼬리)", lambda x: int((x > 0.2).sum())),
                                   최대중앙비_중앙=("최대/중앙", "median")).reindex(VARS).reset_index())
    rep.p("ξ > 0.2 : 드물게 매우 큰 사건이 오는 '충격형'. ξ ≤ 0 : 상한이 있는 '안정형'.")
    for v in ["TP", "Turb", "TOC"]:
        x = t[t["var"] == v].sort_values("ξ(꼬리)", ascending=False)
        if len(x):
            rep.table(x.head(8)[["basin", "station", "ξ(꼬리)", "임계(p95)", "1년 재현", "2년 재현", "관측 최대"]], f"{v}: 충격형 상위 8")
            rep.finding(f"{v} 충격형(ξ>0.2) 측정소 {int((x['ξ(꼬리)'] > 0.2).sum())}곳 — 최대 {x.iloc[0]['station']}(ξ={x.iloc[0]['ξ(꼬리)']:.2f}, 1년 재현 {x.iloc[0]['1년 재현']:.3g})")
    fig, ax = plt.subplots(figsize=(7, 4))
    for v in VARS:
        ax.hist(t.loc[t["var"] == v, "ξ(꼬리)"], bins=20, alpha=0.5, label=v)
    ax.axvline(0.2, color="k", ls="--")
    ax.legend()
    ax.set_xlabel("ξ (GPD 형상모수)")
    rep.fig(fig, "xi_hist.png")
    rep.save()


if __name__ == "__main__":
    main()
