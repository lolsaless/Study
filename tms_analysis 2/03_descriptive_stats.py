# -*- coding: utf-8 -*-
"""
03. 기술통계와 분포 특성
- 방류구별 농도·유량 요약(평균, 중앙값, 분위수, 변동계수, 왜도·첨도)
- 사업장 유형별·규모별·시군별 비교(Kruskal-Wallis)
- 방류수의 화학량론 비(TN/TP, TOC/TN) → 처리공정 특성의 간접 지표
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats

import config as C
from common import Report, load_clean, size_class


def main():
    rep = Report("03_descriptive_stats", "03. 기술통계와 분포 특성",
                 "전체 사업장의 방류 농도·유량 수준과 분포 모양, 유형·규모·지역 간 차이를 본다.")
    df = load_clean(types=None)
    df["TN_TP"] = df["TN"] / df["TP"]
    df["TOC_TN"] = df["TOC"] / df["TN"]
    cols = C.PARAMS + ["pH", "Q", "TN_TP", "TOC_TN"]

    agg = {}
    for c in cols:
        agg[f"{c}_평균"] = (c, "mean")
        agg[f"{c}_중앙"] = (c, "median")
        agg[f"{c}_p05"] = (c, lambda x: x.quantile(0.05))
        agg[f"{c}_p95"] = (c, lambda x: x.quantile(0.95))
        agg[f"{c}_CV"] = (c, lambda x: x.std() / x.mean() if x.mean() else np.nan)
    st = df.groupby("sid").agg(사업장=("site", "first"), 유형=("site_type", "first"), 시군=("sigun", "first"),
                               유효일=("TN", "count"), **agg).reset_index()
    for p in C.PARAMS + ["Q"]:
        sk = df.groupby("sid")[p].agg(lambda x: stats.skew(np.log(x[x > 0])) if (x > 0).sum() > 30 else np.nan)
        st[f"{p}_로그왜도"] = st["sid"].map(sk)
    st["규모"] = size_class(st["Q_중앙"]).astype(str)
    rep.csv(st, "stats_by_sid.csv")

    rep.h("1. 유형별 요약(방류구 중앙값들의 중앙값)")
    show = ["TOC_중앙", "SS_중앙", "TN_중앙", "TP_중앙", "pH_중앙", "Q_중앙", "TN_TP_중앙", "TOC_TN_중앙", "TN_CV", "TP_CV", "Q_CV"]
    t = st.groupby("유형")[show].median().reset_index()
    t.insert(1, "방류구수", st.groupby("유형").size().values)
    rep.table(t)

    rep.h("2. 하수처리시설: 규모별 비교")
    sw = st[st["유형"] == "하수"]
    t2 = sw.groupby("규모")[show].median().reset_index()
    t2.insert(1, "방류구수", sw.groupby("규모").size().reindex(t2["규모"]).values)
    rep.table(t2)
    kw = []
    for c in ["TOC_중앙", "SS_중앙", "TN_중앙", "TP_중앙", "TN_CV", "TP_CV", "Q_CV"]:
        groups = [g[c].dropna().values for _, g in sw.groupby("규모") if g[c].notna().sum() >= 3]
        if len(groups) >= 2:
            h, pval = stats.kruskal(*groups)
            kw.append({"변수": c, "H": h, "p값": pval})
    rep.table(pd.DataFrame(kw), "규모 간 차이 Kruskal-Wallis 검정")
    rep.p("해석 포인트: 소규모 처리장일수록 변동계수(CV)가 큰지, 대규모일수록 TN이 높은지(유입 특성) 등.")

    rep.h("3. 하수처리시설: 농도가 높은/변동이 큰 방류구")
    rep.table(sw.sort_values("TN_중앙", ascending=False)[["sid", "시군", "Q_중앙", "TN_중앙", "TN_p95", "TN_CV"]].head(20), "TN 중앙값 상위 20")
    rep.table(sw.sort_values("TP_중앙", ascending=False)[["sid", "시군", "Q_중앙", "TP_중앙", "TP_p95", "TP_CV"]].head(20), "TP 중앙값 상위 20")
    rep.table(sw.sort_values("TN_CV", ascending=False)[["sid", "시군", "Q_중앙", "TN_중앙", "TN_CV", "Q_CV"]].head(20), "TN 변동계수 상위 20")

    rep.h("4. 방류수 화학량론 비")
    rep.p("TN/TP 비가 매우 높으면 인 제거(총인시설)가 강하고 질소 제거가 약한 공정, 낮으면 반대일 가능성. "
          "TOC/TN 비는 유기물 대비 질소 잔류 정도.")
    rep.table(sw[["TN_TP_중앙", "TOC_TN_중앙"]].describe().T.reset_index().rename(columns={"index": "지표"}), "하수 방류구 분포")

    if st["시군"].notna().any():
        rep.h("5. 시군별(하수, 방류구 중앙값의 중앙값)")
        t5 = sw.groupby("시군")[["TOC_중앙", "SS_중앙", "TN_중앙", "TP_중앙", "Q_중앙"]].median()
        t5["방류구수"] = sw.groupby("시군").size()
        rep.table(t5.sort_values("TN_중앙", ascending=False).reset_index())

    # 그림: 유형별 상자그림
    fig, axes = plt.subplots(1, 4, figsize=(15, 4))
    types = [t for t in ["하수", "폐수", "정수", "산업·기타"] if t in st["유형"].unique()]
    for ax, p in zip(axes, C.PARAMS):
        data = [st.loc[st["유형"] == t, f"{p}_중앙"].dropna() for t in types]
        ax.boxplot(data, showfliers=False)
        ax.set_xticks(range(1, len(types) + 1))
        ax.set_xticklabels(types)
        ax.set_yscale("log")
        ax.set_title(f"{p} 중앙값({C.CONC_UNIT})")
    rep.fig(fig, "box_by_type.png", "방류구별 중앙값 분포, 로그축")

    fig, axes = plt.subplots(1, 4, figsize=(15, 4))
    for ax, p in zip(axes, C.PARAMS):
        ax.scatter(sw["Q_중앙"], sw[f"{p}_중앙"], s=10, alpha=0.6)
        ax.set_xscale("log")
        ax.set_xlabel("유량 중앙값(m3/일)")
        ax.set_title(f"{p} 중앙값 vs 규모")
    rep.fig(fig, "scale_vs_conc.png", "하수처리시설 규모와 방류 농도")

    rep.save()


if __name__ == "__main__":
    main()
