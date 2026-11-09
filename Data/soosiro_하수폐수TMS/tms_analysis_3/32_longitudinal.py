# -*- coding: utf-8 -*-
"""
32. 상류→하류 종단 분석 — 줄기(stations.csv 의 stem·stem_order)별 농도 변화, 인접 구간 악화 검정, 사전백색화 교차상관으로 전달 시간
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

REQUIRES = ["river_daily", "stem"]
LEVEL = "심화"
VARS = ["WT", "EC", "TOC", "TN", "TP", "Chl_a", "Turb"]


def main():
    rep = Report("32_longitudinal", "32. 상류→하류 종단 변화와 전달 시간", level=LEVEL,
                 purpose="같은 줄기에 놓인 측정소를 상류부터 나란히 놓고, 어느 구간에서 수질이 나빠지는지(같은 날 짝비교), "
                         "상류 신호가 며칠 뒤 하류에 나타나는지(사전백색화 교차상관)를 본다.")
    sta = io.load_stations()
    stem = sta.dropna(subset=["stem", "stem_order"])
    if stem.empty:
        return rep.wait("data/meta/stations.csv 의 stem·stem_order 가 비어 있다.", ["측정소 줄기·순서(자료요구서 A-2)"])
    rep.p("⚠ 줄기와 순서는 현재 '추정'이다(stations.csv link_note). 측정소 좌표·하천도로 확인 후 고칠 것.")
    d = io.load_daily(VARS)
    rep.data_info(d)
    prof_rows, pair_rows, lag_rows = [], [], []
    for sname, g in stem.groupby("stem"):
        order = g.sort_values("stem_order")["station"].tolist()
        for v in VARS:
            w = io.wide(d, v, order).reindex(columns=order)
            for s_ in order:
                if s_ in w and w[s_].notna().sum() > 100:
                    prof_rows.append({"줄기": sname, "순서": order.index(s_) + 1, "station": s_, "var": v,
                                      "중앙": w[s_].median(), "여름중앙": w.loc[w.index.month.isin([6, 7, 8, 9]), s_].median()})
            for up, dn in zip(order[:-1], order[1:]):
                if up not in w or dn not in w:
                    continue
                pr = w[[up, dn]].dropna()
                if len(pr) < 100:
                    continue
                lr = (np.log(pr[dn] / pr[up]) if v in C.LOG_VARS else pr[dn] - pr[up]).replace([np.inf, -np.inf], np.nan).dropna()
                p = stats.wilcoxon(lr).pvalue if len(lr) > 20 else np.nan
                pair_rows.append({"줄기": sname, "구간": f"{up}→{dn}", "var": v, "짝일수": len(lr),
                                  "하류/상류": np.exp(lr.median()) if v in C.LOG_VARS else lr.median(), "p": p})
                if v in ["EC", "WT", "TOC"]:
                    a, b = st.deseason(w[up], v), st.deseason(w[dn], v)
                    lag, r, _ = st.ccf_best_lag(st.prewhiten(a), st.prewhiten(b), max_lag=5)
                    r0 = pd.concat([st.prewhiten(a), st.prewhiten(b)], axis=1).dropna().corr().iloc[0, 1]
                    lag_rows.append({"줄기": sname, "구간": f"{up}→{dn}", "var": v, "최대상관 지연(일)": lag, "r": r, "r(지연0)": r0})
    prof, pairs, lags = pd.DataFrame(prof_rows), pd.DataFrame(pair_rows), pd.DataFrame(lag_rows)
    pairs["q"] = st.fdr(pairs["p"])
    rep.csv(prof, "stem_profile.csv")
    rep.csv(pairs, "reach_change.csv")
    rep.h("1. 줄기별 농도 종단(중앙값)")
    for sname in prof["줄기"].unique():
        t = prof[prof["줄기"] == sname].pivot_table(index=["순서", "station"], columns="var", values="중앙").reindex(columns=VARS)
        rep.table(t.round(3), sname, index=True)
    rep.h("2. 수질이 크게 나빠지는 구간(같은 날 짝비교, 하류/상류 비 ≥ 1.3, q<0.05)")
    worse = pairs[(pairs["var"].isin(["TOC", "TN", "TP", "Chl_a"])) & (pairs["하류/상류"] >= 1.3) & (pairs["q"] < 0.05)].sort_values("하류/상류", ascending=False)
    rep.table(worse)
    for _, r in worse.head(5).iterrows():
        rep.finding(f"{r['줄기']} {r['구간']}: {r['var']} 하류가 상류의 {r['하류/상류']:.2f}배(같은 날 {r['짝일수']}일 비교) — 이 구간 유입원 조사 우선")
    better = pairs[(pairs["var"].isin(["TOC", "TP"])) & (pairs["하류/상류"] <= 0.75) & (pairs["q"] < 0.05)]
    if len(better):
        rep.table(better, "개선되는 구간(희석·침강·댐) 하류/상류 ≤ 0.75")
    if len(lags):
        rep.h("3. 상류 신호의 전달 시간(사전백색화 교차상관, ±5일)")
        rep.table(lags.round(3))
        rep.csv(lags, "reach_lag.csv")
        ok = lags[(lags["r"] > 0.2) & (lags["최대상관 지연(일)"] > 0)]
        if len(ok):
            rep.finding(f"상류→하류 지연이 확인된 구간 {len(ok)}건(지연 중앙 {ok['최대상관 지연(일)'].median():.0f}일) — 사고 시 하류 도달 시간 추정에 활용")
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    for ax, v in zip(axes, ["TOC", "TP", "EC"]):
        for sname in prof["줄기"].unique():
            t = prof[(prof["줄기"] == sname) & (prof["var"] == v)].sort_values("순서")
            ax.plot(t["순서"], t["중앙"], marker="o", label=sname)
        ax.set_title(f"{v} 종단(상류→하류)")
        ax.set_xlabel("줄기 내 순서")
    axes[0].legend(fontsize=7)
    rep.fig(fig, "stem_profiles.png")
    rep.save()


if __name__ == "__main__":
    main()
