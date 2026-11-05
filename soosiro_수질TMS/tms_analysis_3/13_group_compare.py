# -*- coding: utf-8 -*-
"""
13. 집단 비교 통계 — 수계 간(Kruskal–Wallis+Dunn, 측정소 단위), 계절 간(Friedman, 측정소 대응), 연도 간(대응 Wilcoxon + HL 이동량)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
from scipy import stats

import config as C
from core import Report, io, st

REQUIRES = ["river_daily"]
LEVEL = "기본"
VARS = ["WT", "EC", "DO", "Turb", "TOC", "TN", "TP", "Chl_a"]


def main():
    rep = Report("13_group_compare", "13. 수계·계절·연도 비교 통계", level=LEVEL,
                 purpose="일자료를 그대로 비교하면 표본이 부풀어(유사반복) 거의 모든 차이가 유의해진다. "
                         "그래서 '측정소'를 분석 단위로 삼아 수계·계절·연도 차이를 효과크기와 함께 검정한다.")
    d = io.load_daily(VARS)
    rep.data_info(d)
    med = d.groupby(["basin", "station"])[VARS].median().reset_index()

    rep.h("1. 수계 간 차이(측정소 중앙값, Kruskal–Wallis + Dunn/Holm)")
    kw, pairs = [], []
    for v in VARS:
        groups = {b: med.loc[med["basin"] == b, v].values for b in C.BASINS}
        H, p, eps2, pr = st.kruskal_dunn(groups)
        kw.append({"항목": v, "H": H, "p": p, "ε²(효과크기)": eps2,
                   **{f"{b} 중앙": np.nanmedian(groups[b]) if len(groups[b]) else np.nan for b in C.BASINS}})
        if len(pr):
            pairs.append(pr.assign(항목=v))
    kw = pd.DataFrame(kw)
    kw["q(FDR)"] = st.fdr(kw["p"])
    rep.table(kw)
    rep.p("ε² 해석: 0.01 작음, 0.08 중간, 0.26 이상 큼.")
    if pairs:
        pr = pd.concat(pairs)
        sig = pr[pr["p_holm"] < 0.05]
        rep.table(sig[["항목", "A", "B", "중앙값A", "중앙값B", "cliffs_delta(B-A)", "p_holm"]], "유의한 수계 쌍(Holm p<0.05)")
        rep.csv(pr, "basin_pairs.csv")
    for _, r in kw[kw["q(FDR)"] < 0.05].iterrows():
        meds = {b: r[f"{b} 중앙"] for b in C.BASINS}
        hi = max(meds, key=lambda k: meds[k] if pd.notna(meds[k]) else -np.inf)
        rep.finding(f"{r['항목']}: 수계 간 차이 유의(ε²={r['ε²(효과크기)']:.2f}), 최고 {hi}(측정소 중앙 {meds[hi]:.3g})")

    rep.h("2. 계절 차이(측정소별 계절 중앙값, Friedman 대응검정)")
    sea = d.groupby(["station", "season"])[VARS].median().reset_index()
    order = ["봄", "여름", "가을", "겨울"]
    fr = []
    for v in VARS:
        w = sea.pivot(index="station", columns="season", values=v).reindex(columns=order).dropna()
        if len(w) < 5:
            continue
        chi, p = stats.friedmanchisquare(*[w[c] for c in order])
        W = chi / (len(w) * 3)          # Kendall W
        fr.append({"항목": v, "측정소": len(w), "chi2": chi, "p": p, "Kendall W": W,
                   **{c: w[c].median() for c in order}, "최고 계절": w.median().idxmax()})
    fr = pd.DataFrame(fr)
    rep.table(fr)
    for _, r in fr.iterrows():
        if r["p"] < 0.05 and r["Kendall W"] > 0.3:
            rep.finding(f"{r['항목']} 계절성 일관(Kendall W={r['Kendall W']:.2f}, 최고 {r['최고 계절']}: 중앙 {r[r['최고 계절']]:.3g})")

    rep.h("3. 연도 간 변화(같은 달만, 측정소 대응 Wilcoxon + Hodges–Lehmann)")
    yrs = sorted(d["year"].unique())
    if len(yrs) >= 2:
        a, b = yrs[-2], yrs[-1]
        common = sorted(set(d.loc[d["year"] == a, "month"]) & set(d.loc[d["year"] == b, "month"]))
        sub = d[d["month"].isin(common)]
        yr_rows, st_rows = [], []
        for v in VARS:
            ym = sub.groupby(["station", "year"])[v].median().unstack()
            if a not in ym or b not in ym:
                continue
            ym = ym[[a, b]].dropna()
            if len(ym) < 6:
                continue
            ratio = np.log(ym[b] / ym[a]) if v in C.LOG_VARS else ym[b] - ym[a]
            ratio = ratio.replace([np.inf, -np.inf], np.nan).dropna()
            w = stats.wilcoxon(ratio)
            yr_rows.append({"항목": v, "측정소": len(ratio), "변화 중앙값": (np.exp(ratio.median()) - 1) * 100 if v in C.LOG_VARS else ratio.median(),
                            "단위": "%" if v in C.LOG_VARS else C.VAR_INFO[v][1], "증가 측정소": int((ratio > 0).sum()),
                            "감소 측정소": int((ratio < 0).sum()), "p": w.pvalue})
            for stn, g in sub.dropna(subset=[v]).groupby("station"):
                xa, xb = g.loc[g["year"] == a, v], g.loc[g["year"] == b, v]
                if len(xa) > 60 and len(xb) > 60:
                    la, lb = (np.log(xa[xa > 0]), np.log(xb[xb > 0])) if v in C.LOG_VARS else (xa, xb)
                    st_rows.append({"station": stn, "var": v, "HL이동": st.hodges_lehmann(la, lb),
                                    "cliffs_delta": st.cliffs_delta(la, lb), "p": stats.mannwhitneyu(xa, xb).pvalue})
        yr = pd.DataFrame(yr_rows)
        rep.p(f"비교: {a} vs {b}, 공통 월 {common}")
        rep.table(yr)
        for _, r in yr[yr["p"] < 0.05].iterrows():
            rep.finding(f"{a}→{b} {r['항목']} 측정소 중앙 변화 {r['변화 중앙값']:+.1f}{r['단위']} (증가 {r['증가 측정소']}·감소 {r['감소 측정소']}곳, p={r['p']:.3g})")
        if st_rows:
            s = pd.DataFrame(st_rows)
            s["q"] = st.fdr(s["p"])
            s["효과"] = pd.cut(s["cliffs_delta"].abs(), [0, 0.147, 0.33, 0.474, 1.01], labels=["무시", "작음", "중간", "큼"], include_lowest=True)
            rep.csv(s, "year_shift_by_station.csv")
            big = s[(s["q"] < 0.05) & (s["효과"].isin(["중간", "큼"]))].sort_values("cliffs_delta")
            rep.table(big, "측정소별로 연도 차이가 '중간 이상'인 경우(Cliff's δ, q<0.05)")
    rep.save()


if __name__ == "__main__":
    main()
