# -*- coding: utf-8 -*-
"""
14. 연중 패턴 '모양' 군집(시계열 형태 군집)
- 방류구별 주별(1~52주) 평균 프로파일을 z-정규화 → 수준은 무시하고 '언제 오르내리는가'만 비교
- K-means(유클리드 = 상관거리와 동등) + (tslearn 있으면) DTW 기반 군집도 함께
- 결과: 겨울 상승형 / 여름 상승형 / 평탄형 등 패턴 그룹과 대표 곡선
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import config as C
from common import Report, load_clean, valid_sids, daily, need

TARGETS = ["TN", "Q", "TP", "TOC"]
K = 4


def weekly_profile(s):
    w = s.groupby(s.index.isocalendar().week.clip(upper=52).values).mean()
    w = w.reindex(range(1, 53)).interpolate(limit_direction="both")
    w = w.rolling(3, center=True, min_periods=1).mean()
    if w.std() == 0 or w.isna().any():
        return None
    return ((w - w.mean()) / w.std()).values


def main():
    rep = Report("14_shape_clustering", "14. 연중 패턴 모양 군집",
                 "농도·유량이 1년 중 언제 오르고 내리는지의 '모양'으로 처리장을 묶는다.")
    skl = need("sklearn", "scikit-learn")
    if skl is None:
        rep.p("scikit-learn 필요")
        rep.save()
        return
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    tsl = need("tslearn")

    df = load_clean()
    df = df[df["sid"].isin(valid_sids(df, "TN", min_days=600))]
    sigun = df.groupby("sid")["sigun"].first()

    allmem = []
    for v in TARGETS:
        rep.h(f"[{v}]")
        prof = {}
        for sid, g in df.groupby("sid"):
            p = weekly_profile(daily(g, v))
            if p is not None:
                prof[sid] = p
        if len(prof) < 10:
            rep.p("방류구 부족")
            continue
        P = pd.DataFrame(prof).T
        sils = {k: silhouette_score(P.values, KMeans(k, n_init=20, random_state=C.RANDOM_STATE).fit_predict(P.values))
                for k in range(2, 7)}
        km = KMeans(K, n_init=50, random_state=C.RANDOM_STATE).fit(P.values)
        lab = km.labels_
        rep.kv({"방류구 수": len(P), "실루엣(k=2~6)": ", ".join(f"{k}:{s:.2f}" for k, s in sils.items()), "사용 k": K})
        cent = pd.DataFrame(km.cluster_centers_, columns=range(1, 53))
        desc = []
        for k in range(K):
            c = cent.loc[k]
            desc.append({"군집": k, "방류구수": int((lab == k).sum()), "최고주차": int(c.idxmax()), "최저주차": int(c.idxmin()),
                         "진폭(z)": c.max() - c.min(),
                         "1~8주 평균z": c.loc[1:8].mean(), "27~35주 평균z": c.loc[27:35].mean(),
                         "주요시군": ", ".join(pd.Series(P.index[lab == k]).map(sigun).value_counts().head(3).index.astype(str))})
        rep.table(pd.DataFrame(desc), "군집 대표 곡선 요약(z-점수)", digits=2)
        rep.p("1~8주(1~2월) 평균z가 양수면 겨울 상승형, 27~35주(7~8월)가 양수면 여름 상승형.")
        mem = pd.DataFrame({"sid": P.index, "시군": P.index.map(sigun), "항목": v, "군집_km": lab})

        if tsl is not None:
            from tslearn.clustering import TimeSeriesKMeans
            dtw = TimeSeriesKMeans(n_clusters=K, metric="dtw", max_iter=20, random_state=C.RANDOM_STATE).fit(P.values[:, :, None])
            mem["군집_dtw"] = dtw.labels_
            ct = pd.crosstab(mem["군집_km"], mem["군집_dtw"])
            rep.table(ct.reset_index(), "K-means vs DTW 군집 교차표")
        allmem.append(mem)

        fig, axes = plt.subplots(1, K, figsize=(4 * K, 3.2), sharey=True)
        for k, ax in enumerate(axes):
            for row in P.values[lab == k]:
                ax.plot(range(1, 53), row, color="gray", alpha=0.15, lw=0.6)
            ax.plot(range(1, 53), cent.loc[k], color="C0", lw=2)
            ax.set_title(f"{v} 군집 {k} (n={(lab == k).sum()})")
            ax.set_xlabel("주차")
        rep.fig(fig, f"{v}_shape_clusters.png")

    if allmem:
        rep.csv(pd.concat(allmem), "shape_cluster_membership.csv")
    rep.save()


if __name__ == "__main__":
    main()
