# -*- coding: utf-8 -*-
"""
11. 기술통계·분포 — 측정소·수계별 수준과 변동, 영양염 제한 진단(TN:TP), 수계 비교 그림
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats

import config as C
from core import Report, io, BASIN_COLORS

REQUIRES = ["river_daily"]
LEVEL = "기본"
VARS = C.CORE_VARS + ["DO_sat"]


def main():
    rep = Report("11_descriptive", "11. 기술통계와 분포", level=LEVEL,
                 purpose="측정소·수계별 수질 수준과 변동폭을 정리하고, TN:TP 비로 영양염 제한 상태를 진단한다.")
    d = io.load_daily(C.CORE_VARS)
    rep.data_info(d)
    rows = []
    for (b, stn), g in d.groupby(["basin", "station"]):
        for v in VARS:
            x = g[v].dropna()
            if len(x) < 30:
                continue
            q = x.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
            rows.append({"basin": b, "station": stn, "waterbody": g["waterbody"].iloc[0], "var": v, "n": len(x),
                         "평균": x.mean(), "표준편차": x.std(), "CV": x.std() / x.mean() if x.mean() else np.nan,
                         "p5": q[0.05], "p25": q[0.25], "중앙값": q[0.5], "p75": q[0.75], "p95": q[0.95],
                         "p95/p50": q[0.95] / q[0.5] if q[0.5] else np.nan, "왜도": stats.skew(x)})
    t = pd.DataFrame(rows)
    rep.csv(t, "stats_by_station.csv")

    rep.h("1. 수계별 요약(측정소 중앙값의 중앙값)")
    bs = t.pivot_table(index="var", columns="basin", values="중앙값", aggfunc="median").reindex(VARS)
    rep.table(bs, index=True)
    cv = t.pivot_table(index="var", columns="basin", values="CV", aggfunc="median").reindex(VARS)
    rep.table(cv, "변동계수(CV) 중앙값 — 클수록 날마다 출렁임", index=True)

    rep.h("2. 항목별 최고·최저 측정소(중앙값 기준)")
    for v in ["TOC", "TP", "TN", "Chl_a", "EC"]:
        x = t[t["var"] == v].sort_values("중앙값")
        if len(x) >= 6:
            rep.table(pd.concat([x.head(3), x.tail(5)])[["basin", "station", "waterbody", "중앙값", "p95", "CV"]], f"{v}: 하위 3 / 상위 5")
            top = x.iloc[-1]
            rep.finding(f"{v} 중앙값 최고: {top['station']}({top['basin']}) {top['중앙값']:.3g} — 최저 {x.iloc[0]['station']} {x.iloc[0]['중앙값']:.3g} ({top['중앙값'] / x.iloc[0]['중앙값']:.0f}배)")

    rep.h("3. 영양염 제한 진단(TN:TP 질량비)")
    rep.p("질량비 기준(Guildford & Hecky 2000 몰비 20·50 환산): < 9 질소 제한 가능, 9~22 공동 제한, > 22 인 제한. "
          "자동측정망 TN·TP 는 총량이라 생물이용 가능 형태와 다를 수 있다.")
    np_rows = []
    for (b, stn), g in d.dropna(subset=["TN", "TP"]).groupby(["basin", "station"]):
        if len(g) < 60:
            continue
        r = (g["TN"] / g["TP"]).replace([np.inf, -np.inf], np.nan).dropna()
        summer = (g.loc[g["month"].between(6, 9), "TN"] / g.loc[g["month"].between(6, 9), "TP"]).median()
        np_rows.append({"basin": b, "station": stn, "TN:TP 중앙": r.median(), "여름(6~9월)": summer,
                        "인제한일%": (r > 22).mean() * 100, "질소제한일%": (r < 9).mean() * 100})
    npt = pd.DataFrame(np_rows).sort_values("TN:TP 중앙")
    npt["판정"] = pd.cut(npt["TN:TP 중앙"], [0, 9, 22, np.inf], labels=["질소 제한 가능", "공동 제한", "인 제한"])
    rep.table(npt)
    rep.csv(npt, "np_ratio.csv")
    vc = npt["판정"].value_counts()
    rep.finding(f"TN:TP 질량비 판정 — 인 제한 {vc.get('인 제한', 0)}곳, 공동 제한 {vc.get('공동 제한', 0)}곳, 질소 제한 가능 {vc.get('질소 제한 가능', 0)}곳"
                f" (여름 중앙 {npt['여름(6~9월)'].median():.0f})")

    fig, axes = plt.subplots(2, 4, figsize=(16, 7))
    for ax, v in zip(axes.flat, ["WT", "EC", "DO", "Turb", "TOC", "TN", "TP", "Chl_a"]):
        data = [d.loc[d["basin"] == b, v].dropna() for b in C.BASINS]
        bp = ax.boxplot([x[x > 0] if v in C.LOG_VARS else x for x in data], showfliers=False, patch_artist=True)
        for patch, b in zip(bp["boxes"], C.BASINS):
            patch.set_facecolor(BASIN_COLORS[b])
        ax.set_xticks(range(1, 5), C.BASINS)
        if v in C.LOG_VARS:
            ax.set_yscale("log")
        ax.set_title(f"{v} ({C.VAR_INFO[v][1]})")
    fig.tight_layout()
    rep.fig(fig, "basin_boxplots.png", "수계별 일평균 분포(이상치 제외)")
    rep.save()


if __name__ == "__main__":
    main()
