# -*- coding: utf-8 -*-
"""
21. 추세 — 계절 Mann–Kendall + Sen 기울기(%/년), FDR 보정, 자료 기간에 따른 검정력 안내
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import config as C
from core import Report, io, st

REQUIRES = ["river_daily"]
LEVEL = "중급"
VARS = ["WT", "EC", "DO", "Turb", "TOC", "TN", "TP", "Chl_a"]


def main():
    rep = Report("21_trend", "21. 장기 추세(계절 Mann–Kendall)", level=LEVEL,
                 purpose="계절성을 통제한 단조 추세를 측정소×항목마다 검정한다. 자료가 쌓일수록(2026년 이후 추가) 검정력이 커지도록 "
                         "기간 제한 없이 작성했다.")
    d = io.load_daily(VARS)
    rep.data_info(d)
    years = d["year"].nunique()
    if years < 3:
        rep.p(f"⚠ 현재 자료는 {years}개 연도라 같은 달 비교쌍이 달마다 {years * (years - 1) // 2}개뿐이다. "
              "계절 MK 의 최소 p 값이 커서 유의한 추세가 거의 나올 수 없다 → **추세가 아니라 '방향 예비 신호'로만 읽는다.** "
              "연도 간 차이의 엄밀한 검정은 13번(대응 Wilcoxon)을 본다. 3년 이상 쌓이면 이 표가 본 결과가 된다.")
    rows = []
    for b, stn, v, s in io.iter_series(d, VARS):
        mon = s.resample("MS").median()
        if mon.notna().sum() < 18:
            continue
        p, slope, trend = st.seasonal_mk(mon)
        rows.append({"basin": b, "station": stn, "var": v, "개월": int(mon.notna().sum()), "p": p,
                     "Sen(단위/년)": slope, "Sen(%/년)": slope / mon.median() * 100 if mon.median() else np.nan, "방향": trend})
    t = pd.DataFrame(rows)
    t["q"] = st.fdr(t["p"])
    rep.csv(t, "trend_by_station.csv")
    rep.h("1. 항목별 요약")
    s = t.groupby("var").agg(측정소=("station", "size"), 증가경향=("Sen(%/년)", lambda x: int((x > 0).sum())),
                             감소경향=("Sen(%/년)", lambda x: int((x < 0).sum())), Sen중앙_pct=("Sen(%/년)", "median"),
                             p_lt_005=("p", lambda x: int((x < 0.05).sum())), q_lt_005=("q", lambda x: int((x < 0.05).sum()))).reindex(VARS)
    rep.table(s, index=True)
    # 부호 검정: 측정소들의 증가/감소 경향이 한쪽으로 쏠렸나(측정소 단위 이항검정)
    from scipy.stats import binomtest
    for v, r in s.dropna().iterrows():
        n = int(r["증가경향"] + r["감소경향"])
        if n >= 10:
            bt = binomtest(int(r["증가경향"]), n, 0.5)
            if bt.pvalue < 0.01:
                up = r["증가경향"] >= r["감소경향"]
                k = int(r["증가경향"] if up else r["감소경향"])
                rep.finding(f"{v}: 측정소 {n}곳 중 {k}곳이 {'증가' if up else '감소'} 경향(이항검정 p={bt.pvalue:.2g}, Sen 중앙 {r['Sen중앙_pct']:+.1f}%/년) — 2개 연도 비교라 예비 신호(연간 기상 차이일 수 있음)")
    rep.h("2. 변화율이 큰 측정소(|Sen| 상위)")
    for v in ["TOC", "TP", "TN", "Chl_a"]:
        x = t[t["var"] == v].dropna(subset=["Sen(%/년)"]).sort_values("Sen(%/년)")
        if len(x):
            rep.table(pd.concat([x.head(5), x.tail(5)])[["basin", "station", "Sen(%/년)", "p", "q"]], f"{v}: 감소 5 / 증가 5")
    fig, axes = plt.subplots(1, len(VARS), figsize=(18, 3.2))
    for ax, v in zip(axes, VARS):
        ax.hist(t.loc[t["var"] == v, "Sen(%/년)"].clip(-100, 100).dropna(), bins=25)
        ax.axvline(0, color="k", lw=0.8)
        ax.set_title(v)
    rep.fig(fig, "sen_hist.png", "측정소별 Sen 기울기(%/년) 분포")
    rep.save()


if __name__ == "__main__":
    main()
