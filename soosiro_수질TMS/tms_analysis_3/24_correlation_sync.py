# -*- coding: utf-8 -*-
"""
24. 항목 간 관계와 측정소 간 동조성 — 측정소 내 Spearman·편상관(Chl-a~TP | 수온), 계절 제거 편차의 수계 공통 신호(PCA 설명비율)
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
VARS = ["WT", "EC", "DO", "Turb", "TOC", "TN", "TP", "Chl_a"]


def partial_spearman(x, y, z):
    """z 를 통제한 x–y 순위 편상관"""
    r = pd.DataFrame({"x": x, "y": y, "z": z}).dropna().rank()
    if len(r) < 30:
        return np.nan, np.nan
    rx = r["x"] - np.polyval(np.polyfit(r["z"], r["x"], 1), r["z"])
    ry = r["y"] - np.polyval(np.polyfit(r["z"], r["y"], 1), r["z"])
    return stats.pearsonr(rx, ry)


def main():
    rep = Report("24_correlation_sync", "24. 항목 간 관계와 측정소 간 동조성", level=LEVEL,
                 purpose="측정소 안에서 항목들이 어떻게 함께 움직이는지, 그리고 같은 수계의 측정소들이 같은 날 함께 움직이는 정도"
                         "(광역 요인 = 기상)를 본다.")
    d = io.load_daily(VARS)
    rep.data_info(d)

    rep.h("1. 측정소 내 항목 간 Spearman 상관(측정소 중앙값)")
    mats = []
    for stn, g in d.groupby("station"):
        x = g[VARS].dropna(axis=1, thresh=200)
        if x.shape[1] >= 4:
            mats.append(x.corr(method="spearman").stack().rename(stn))
    M = pd.concat(mats, axis=1).median(axis=1).unstack().reindex(index=VARS, columns=VARS)
    rep.table(M.round(2), index=True)
    rep.csv(pd.concat(mats, axis=1).reset_index(), "corr_by_station.csv")

    rep.h("2. Chl-a 와 영양염: 수온을 통제한 편상관")
    rows = []
    for (b, stn), g in d.groupby(["basin", "station"]):
        for nut in ["TP", "TN"]:
            if g[["Chl_a", nut, "WT"]].dropna().shape[0] > 150:
                r0 = stats.spearmanr(g["Chl_a"], g[nut], nan_policy="omit")[0]
                rp, p = partial_spearman(g["Chl_a"], g[nut], g["WT"])
                rows.append({"basin": b, "station": stn, "영양염": nut, "ρ(단순)": r0, "ρ(수온 통제)": rp, "p": p})
    pc = pd.DataFrame(rows)
    pc["q"] = st.fdr(pc["p"])
    rep.table(pc.groupby(["영양염", "basin"])[["ρ(단순)", "ρ(수온 통제)"]].median().round(2), "수계별 중앙값", index=True)
    rep.csv(pc, "chla_nutrient_partial.csv")
    tp = pc[pc["영양염"] == "TP"]
    rep.finding(f"Chl-a~TP 수온 통제 편상관: 양(+) 유의 {int(((tp['q'] < 0.05) & (tp['ρ(수온 통제)'] > 0)).sum())}곳, "
                f"음(−) 유의 {int(((tp['q'] < 0.05) & (tp['ρ(수온 통제)'] < 0)).sum())}곳 / {len(tp)}곳 — "
                "음의 관계는 조류가 인을 흡수하거나 강우 TP 유입과 조류 감소가 겹치는 곳")

    rep.h("3. 수계 공통 신호(계절 제거 편차의 제1주성분 설명비율)")
    rows = []
    for v in ["EC", "Turb", "TOC", "TP", "WT", "Chl_a"]:
        for b in C.BASINS:
            w = io.wide(d[d["basin"] == b], v)
            a = pd.DataFrame({c: st.deseason(w[c], v) for c in w.columns})
            a = a.loc[:, a.notna().mean() > 0.6].dropna(thresh=int(0.7 * a.shape[1]) if a.shape[1] else 1)
            if a.shape[1] < 4 or len(a) < 200:
                continue
            z = (a - a.mean()) / a.std()
            z = z.fillna(0)
            ev = np.linalg.eigvalsh(np.cov(z.T.values))
            corr = z.corr().where(~np.eye(z.shape[1], dtype=bool)).stack()
            rows.append({"항목": v, "수계": b, "측정소": a.shape[1], "PC1 설명비율": ev[-1] / ev.sum(),
                         "측정소 쌍 상관 중앙": corr.median()})
    sy = pd.DataFrame(rows)
    rep.table(sy.round(3))
    rep.p("PC1 설명비율이 높을수록 같은 수계 측정소들이 같은 날 함께 오르내린다(강우 등 광역 요인). 낮으면 국지 요인이 지배한다.")
    if len(sy):
        hi = sy.sort_values("PC1 설명비율", ascending=False).iloc[0]
        lo = sy.sort_values("PC1 설명비율").iloc[0]
        rep.finding(f"수계 공통 신호 최대: {hi['수계']} {hi['항목']} {hi['PC1 설명비율']:.0%}, 최소: {lo['수계']} {lo['항목']} {lo['PC1 설명비율']:.0%} — 광역(기상) vs 국지 요인의 비중")
    fig, ax = plt.subplots(figsize=(6, 5))
    im = ax.imshow(M.values, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(VARS)), VARS, rotation=45)
    ax.set_yticks(range(len(VARS)), VARS)
    fig.colorbar(im)
    rep.fig(fig, "corr_matrix.png", "측정소 내 항목 간 Spearman ρ(측정소 중앙)")
    rep.save()


if __name__ == "__main__":
    main()
