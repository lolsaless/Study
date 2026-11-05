# -*- coding: utf-8 -*-
"""
12. 생활환경기준 등급·목표 달성 — 연평균 등급 + '등급 판정 신뢰도'(블록 부트스트랩) + 일 초과빈도
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
LEVEL = "기본"


def grade_of(x, thr, lower_is_better=True):
    if pd.isna(x):
        return None
    for g, t in zip(C.GRADES, thr):
        if (x <= t) if lower_is_better else (x >= t):
            return g
    return C.GRADES[-1]


def main():
    rep = Report("12_wq_grade", "12. 생활환경기준 등급과 목표 달성 신뢰도", level=LEVEL,
                 purpose="연평균으로 하천·호소 생활환경기준 등급을 매기고, 자기상관을 고려한 부트스트랩으로 "
                         "'그 등급 판정이 얼마나 확실한지'와 목표 등급 달성 확률을 함께 제시한다(기존 분석에 없던 불확실성 평가).")
    d = io.load_daily(["TOC", "TP", "TN", "Chl_a", "DO"])
    rep.data_info(d)
    sta = io.load_stations().set_index("station")
    rows = []
    for (b, stn, yr), g in d.groupby(["basin", "station", "year"]):
        wb = g["waterbody"].iloc[0]
        stdtab = C.LAKE_STD if wb == "호소" else C.RIVER_STD
        target = sta["target_grade"].get(stn) if "target_grade" in sta and pd.notna(sta["target_grade"].get(stn)) else C.TARGET_GRADE
        tgt_i = C.GRADES.index(target)
        for v, thr in stdtab.items():
            x = g[v].dropna()
            if len(x) < 180:          # 연평균은 반년 이상 자료가 있을 때만
                continue
            low_better = v != "DO"
            m = x.mean()
            gp = grade_of(m, thr, low_better)
            boot = st.block_bootstrap(x.values, np.mean, block=14, n=500)
            gb = pd.Series([grade_of(z, thr, low_better) for z in boot])
            p_same = float((gb == gp).mean()) if len(gb) else np.nan
            p_meet = float(gb.map(lambda z: C.GRADES.index(z) <= tgt_i).mean()) if len(gb) else np.nan
            lim = thr[tgt_i] if tgt_i < len(thr) else np.inf
            exceed = float((x > lim).mean() if low_better else (x < lim).mean())
            rows.append({"basin": b, "station": stn, "waterbody": wb, "year": yr, "var": v, "n": len(x),
                         "연평균": m, "CI95_하": np.quantile(boot, 0.025) if len(boot) else np.nan,
                         "CI95_상": np.quantile(boot, 0.975) if len(boot) else np.nan,
                         "등급": gp, "등급확률": p_same, "목표": target, "목표달성확률": p_meet, "목표초과일%": exceed * 100})
    t = pd.DataFrame(rows)
    rep.csv(t, "grade_by_station_year.csv")

    rep.h("1. 항목별 등급 분포(측정소·연도)")
    for v in ["TOC", "TP"]:
        x = t[t["var"] == v]
        tab = x.pivot_table(index="year", columns="등급", values="station", aggfunc="count", fill_value=0)
        tab = tab.reindex(columns=[g for g in C.GRADES if g in tab.columns])
        rep.table(tab, f"{v} 연평균 등급(측정소 수)", index=True)

    rep.h("2. 목표 등급 미달성 측정소(최근 연도)")
    last = t[t["year"] == t["year"].max()]
    miss = last[last["목표달성확률"] < 0.5].sort_values("목표달성확률")
    rep.table(miss[["basin", "station", "var", "연평균", "등급", "목표", "목표달성확률", "목표초과일%"]])
    rep.finding(f"{int(t['year'].max())}년 목표({C.TARGET_GRADE}등급 기본) 미달성 가능성이 큰(달성확률<50%) 측정소×항목 {len(miss)}건 — "
                f"TOC {int((miss['var'] == 'TOC').sum())}, TP {int((miss['var'] == 'TP').sum())}")

    rep.h("3. 등급 판정이 불확실한 경우(경계 근처)")
    unc = t[(t["등급확률"] < 0.8)].sort_values("등급확률")
    rep.p("등급확률 = 부트스트랩 연평균이 같은 등급으로 나올 확률. 0.8 미만이면 1년 자료로는 등급이 바뀔 수 있는 '경계 측정소'다.")
    rep.table(unc[["basin", "station", "year", "var", "연평균", "CI95_하", "CI95_상", "등급", "등급확률"]])
    rep.finding(f"등급 판정 신뢰도 80% 미만(경계) {len(unc)}건 / 전체 {len(t)}건 — 이 측정소들은 다년 평균·불확실성 표기가 필요")

    rep.h("4. 연도 간 등급 변화")
    pv = t.pivot_table(index=["station", "var"], columns="year", values="등급", aggfunc="first")
    yrs = sorted(t["year"].unique())
    if len(yrs) >= 2:
        a, b = yrs[-2], yrs[-1]
        ch = pv.dropna(subset=[a, b])
        ch = ch[ch[a] != ch[b]].reset_index()
        ch["변화"] = [("악화" if C.GRADES.index(y) > C.GRADES.index(x) else "개선") for x, y in zip(ch[a], ch[b])]
        rep.table(ch, f"{a}→{b} 등급이 바뀐 측정소×항목")
        rep.finding(f"{a}→{b} 등급 변화: 개선 {int((ch['변화'] == '개선').sum())}건, 악화 {int((ch['변화'] == '악화').sum())}건")

    x = t[(t["var"] == "TP") & (t["year"] == t["year"].max())].sort_values("연평균")
    if len(x):
        fig, ax = plt.subplots(figsize=(8, max(5, len(x) * 0.16)))
        y = np.arange(len(x))
        ax.errorbar(x["연평균"], y, xerr=[x["연평균"] - x["CI95_하"], x["CI95_상"] - x["연평균"]], fmt="o", ms=3)
        for t_ in C.RIVER_STD["TP"]:
            ax.axvline(t_, color="gray", lw=0.6, ls="--")
        ax.set_yticks(y, x["station"], fontsize=6)
        ax.set_xscale("log")
        ax.set_xlabel("TP 연평균(mg/L, 95% 블록부트스트랩 구간) · 점선 = 하천 등급 경계")
        rep.fig(fig, "tp_grade_ci.png", "TP 연평균과 신뢰구간 — 구간이 점선을 걸치면 등급 불확실")
    rep.save()


if __name__ == "__main__":
    main()
