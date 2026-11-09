# -*- coding: utf-8 -*-
"""
22. 일주기(하루 안 변동)와 산소 대사 — DO·pH 일교차, 포화도, 저산소·과포화 일수, 광합성 지표와 Chl-a 의 관계, 시각별 패턴
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats

import config as C
from core import Report, io, st

REQUIRES = ["river_daily"]
LEVEL = "중급"


def main():
    rep = Report("22_diel_oxygen", "22. 하루 안 변동(일주기)과 산소 대사", level=LEVEL,
                 purpose="일평균만으로는 보이지 않는 '낮에는 과포화, 새벽에는 저산소'를 일 최소·최대값과 시간자료로 본다. "
                         "DO·pH 의 일교차는 광합성-호흡(하천 대사)의 세기이며 부영양화의 직접 지표다(v2 에 없던 분석).")
    d = io.load_daily(["WT", "pH", "DO", "Chl_a", "TP", "EC"], minmax=True)
    rep.data_info(d)
    d["dDO"] = d["DO_max"] - d["DO_min"]
    d["dpH"] = d["pH_max"] - d["pH_min"]
    d["dWT"] = d["WT_max"] - d["WT_min"]
    rows = []
    for (b, stn), g in d.groupby(["basin", "station"]):
        g = g.dropna(subset=["DO"])
        if len(g) < C.MIN_DAYS:
            continue
        summer = g[g["month"].between(6, 9)]
        r = {"basin": b, "station": stn, "waterbody": g["waterbody"].iloc[0], "일수": len(g),
             "DO일교차_중앙": g["dDO"].median(), "DO일교차_여름p90": summer["dDO"].quantile(0.9) if len(summer) else np.nan,
             "pH일교차_중앙": g["dpH"].median(),
             "저산소일(DOmin<5)": int((g["DO_min"] < C.HYPOXIA_DO).sum()),
             "과포화일(최대>120%)": int((g["DO_sat_max"] > C.SUPERSAT_PCT).sum()),
             "포화도_여름중앙": summer["DO_sat"].median() if len(summer) else np.nan}
        x = g.dropna(subset=["dDO", "Chl_a"])
        if len(x) > 60:
            r["ρ(DO일교차,Chl-a)"], r["p_chl"] = stats.spearmanr(x["dDO"], x["Chl_a"])
        x = g.dropna(subset=["dDO", "dpH"])
        if len(x) > 60:
            r["ρ(DO일교차,pH일교차)"] = stats.spearmanr(x["dDO"], x["dpH"])[0]
        rows.append(r)
    t = pd.DataFrame(rows).sort_values("DO일교차_여름p90", ascending=False)
    rep.csv(t, "diel_by_station.csv")

    rep.h("1. 산소 일교차가 큰(대사가 활발한) 측정소")
    rep.table(t.head(20))
    top = t.head(5)
    rep.finding("여름 DO 일교차(p90) 상위: " + ", ".join(f"{a} {b:.1f} mg/L" for a, b in zip(top["station"], top["DO일교차_여름p90"])))
    hyp = t[t["저산소일(DOmin<5)"] > 0].sort_values("저산소일(DOmin<5)", ascending=False)
    rep.finding(f"하루 중 한 번이라도 DO<5 mg/L 인 날이 있는 측정소 {len(hyp)}곳 — 최다 "
                + ", ".join(f"{a} {b}일" for a, b in zip(hyp["station"].head(4), hyp["저산소일(DOmin<5)"].head(4))) if len(hyp) else "일 최저 DO<5 mg/L 인 날이 있는 측정소 없음")
    sup = t["과포화일(최대>120%)"]
    rep.finding(f"DO 최대 포화도 120% 초과일이 30일 이상인 측정소 {int((sup >= 30).sum())}곳(광합성 과다 = 조류 번성 신호)")
    if "ρ(DO일교차,Chl-a)" in t:
        x = t["ρ(DO일교차,Chl-a)"].dropna()
        rep.finding(f"DO 일교차와 Chl-a 의 측정소별 상관 중앙 ρ={x.median():.2f} (양의 상관 {int((x > 0.3).sum())}/{len(x)}곳) — 일교차가 조류 활동 지표로 쓸 만함")

    rep.h("2. 월별 DO 일교차(수계별 측정소 중앙)")
    m = d.groupby(["basin", "station", "month"])["dDO"].median().groupby(["basin", "month"]).median().unstack(0)
    rep.table(m.round(2), index=True)

    h = io.load_hourly()
    if h is not None and "DO" in h:
        rep.h("3. 시각별 패턴(시간자료)")
        h = h[["basin", "station", "datetime", "DO", "pH", "WT"] + (["Chl_a"] if "Chl_a" in h else [])].dropna(subset=["DO"])
        h = h[h["datetime"].dt.month.between(6, 9)]
        h["hour"] = h["datetime"].dt.hour
        h["dDO_anom"] = h["DO"] - h.groupby(["station", h["datetime"].dt.date])["DO"].transform("mean")
        prof = h.groupby(["station", "hour"])["dDO_anom"].mean().unstack()
        peak = pd.DataFrame({"DO최고시각": prof.idxmax(axis=1), "DO최저시각": prof.idxmin(axis=1),
                             "평균진폭": prof.max(axis=1) - prof.min(axis=1)}).sort_values("평균진폭", ascending=False)
        rep.table(peak.head(15), "여름(6~9월) DO 시각 패턴 — 진폭 상위", index=True)
        rep.csv(peak.reset_index(), "do_hour_profile.csv")
        rep.finding(f"여름 DO 최고 시각 최빈 {int(peak['DO최고시각'].mode().iloc[0])}시, 최저 {int(peak['DO최저시각'].mode().iloc[0])}시 — "
                    "일 1회 채수(주간)는 저산소 위험을 과소평가")
        fig, ax = plt.subplots(figsize=(8, 4))
        for stn in peak.head(8).index:
            ax.plot(prof.columns, prof.loc[stn], label=stn)
        ax.set_xlabel("시각")
        ax.set_ylabel("DO - 그날 평균 (mg/L)")
        ax.legend(fontsize=7, ncol=2)
        rep.fig(fig, "do_hour_profile.png", "여름 DO 시각 패턴(진폭 상위 8곳)")
    else:
        rep.p("시간자료(data/standard/river_hourly.csv.gz)가 없어 시각 분석은 생략했다(01번을 xlsx 로 실행하면 생김).")

    fig, ax = plt.subplots(figsize=(6, 5))
    x = t.dropna(subset=["DO일교차_여름p90", "포화도_여름중앙"])
    ax.scatter(x["포화도_여름중앙"], x["DO일교차_여름p90"], s=14)
    for r in x.head(8).itertuples():
        ax.annotate(r.station, (r.포화도_여름중앙, r.DO일교차_여름p90), fontsize=7)
    ax.set_xlabel("여름 DO 포화도 중앙(%)")
    ax.set_ylabel("여름 DO 일교차 p90 (mg/L)")
    rep.fig(fig, "diel_scatter.png")
    rep.save()


if __name__ == "__main__":
    main()
