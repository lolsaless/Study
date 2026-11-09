# -*- coding: utf-8 -*-
"""
12. 처리장 간 동조성(공간 일관성)과 공통 신호 분해
- 방류구별 일 편차(계절 제거)를 모아 처리장 간 상관행렬 → 계층 군집(어떤 처리장들이 같이 움직이나)
- 같은 시군 안 vs 다른 시군 간 평균 상관 비교 → 공간적으로 가까울수록 같이 움직이는지
- PCA: 첫 주성분(도 전체 공통 신호)이 각 처리장 변동을 몇 % 설명하나
  → 유량에서 공통 신호 설명력 = '광역 기상 영향'의 크기, 나머지 = 처리장 고유 요인
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.cluster.hierarchy import linkage, fcluster, dendrogram
from scipy.spatial.distance import squareform

import config as C
from common import Report, load_clean, valid_sids, daily, anomaly

TARGETS = ["Q", "TN", "TP"]
MIN_COVER = 0.8
N_CLUSTERS = 6


def main():
    rep = Report("12_cross_site_sync", "12. 처리장 간 동조성과 공통 신호",
                 "여러 처리장이 같은 날 같이 움직이는 정도(광역 요인)와 처리장 고유 변동을 분리한다.")
    df = load_clean()
    df = df[df["sid"].isin(valid_sids(df, "TN"))]
    sigun = df.groupby("sid")["sigun"].first()

    for v in TARGETS:
        rep.h(f"[{v}]")
        A = {}
        for sid, g in df.groupby("sid"):
            A[sid] = anomaly(daily(g, v), log=True)
        A = pd.DataFrame(A)
        A = A.loc[:, A.notna().mean() >= MIN_COVER]
        rep.kv({"분석 방류구(보유율≥80%)": A.shape[1], "기간 일수": A.shape[0]})
        if A.shape[1] < 10:
            rep.p("방류구가 너무 적어 건너뜀.")
            continue
        # pandas 신버전(Copy-on-Write)에서는 R.values 가 읽기 전용 → 복사본 배열로 수정 후 다시 DataFrame 생성
        R0 = A.corr(min_periods=200)
        Rv = R0.to_numpy(dtype=float, copy=True)
        Rv = np.nan_to_num(Rv, nan=0.0)
        np.fill_diagonal(Rv, 1.0)
        R = pd.DataFrame(Rv, index=R0.index, columns=R0.columns)

        # 시군 내/간 상관
        iu = np.triu_indices(len(R), 1)
        pairs = pd.DataFrame({"a": np.asarray(R.index)[iu[0]], "b": np.asarray(R.columns)[iu[1]], "r": Rv[iu]})
        sa = pairs["a"].map(sigun).astype(object)
        sb = pairs["b"].map(sigun).astype(object)
        pairs["같은시군"] = (sa.notna() & sb.notna() & (sa == sb)).to_numpy()
        same_site = (pairs["a"].astype(str).str.split("#").str[0] == pairs["b"].astype(str).str.split("#").str[0]).to_numpy()
        rep.table(pd.DataFrame({
            "구분": ["같은 사업장(다른 방류구)", "같은 시군(다른 사업장)", "다른 시군"],
            "평균상관": [pairs.loc[same_site, "r"].mean(), pairs.loc[pairs["같은시군"] & ~same_site, "r"].mean(),
                     pairs.loc[~pairs["같은시군"], "r"].mean()],
            "쌍 수": [int(same_site.sum()), int((pairs["같은시군"] & ~same_site).sum()), int((~pairs["같은시군"]).sum())]}),
            "공간 근접성과 동조성", digits=3)
        rep.csv(pairs.sort_values("r", ascending=False), f"{v}_pair_corr.csv")
        rep.table(pairs[~same_site].sort_values("r", ascending=False).head(15), "가장 같이 움직이는 사업장 쌍(상위 15)", digits=3)

        # 계층 군집
        n_cl = min(N_CLUSTERS, len(R) - 1)
        D = 1.0 - Rv.copy()
        D = (D + D.T) / 2.0                      # 대칭 보장(부동소수 오차)
        np.fill_diagonal(D, 0.0)
        D = np.clip(D, 0.0, 2.0)
        Z = linkage(squareform(D, checks=False), method="average")
        lab = fcluster(Z, n_cl, criterion="maxclust")
        cl = pd.DataFrame({"sid": np.asarray(R.index), "군집": lab,
                           "시군": [sigun.get(s, np.nan) for s in R.index]})
        pos = {s: i for i, s in enumerate(R.index)}
        within = []
        for k, gg in cl.groupby("군집"):
            idx = gg["sid"].tolist()
            ii = [pos[s] for s in idx]
            sub = Rv[np.ix_(ii, ii)]
            within.append({"군집": k, "방류구수": len(idx),
                           "군집내평균상관": sub[np.triu_indices(len(idx), 1)].mean() if len(idx) > 1 else np.nan,
                           "주요시군": ", ".join(gg["시군"].value_counts().head(4).index.astype(str))})
        rep.table(pd.DataFrame(within), f"계층 군집({n_cl}개) 요약", digits=3)
        rep.csv(cl, f"{v}_clusters.csv")

        # PCA (결측은 0=편차 없음으로 대체)
        X = A.fillna(0).to_numpy(dtype=float, copy=True)
        X = (X - X.mean(0)) / (X.std(0) + 1e-9)
        U, S, Vt = np.linalg.svd(X, full_matrices=False)
        ev = S ** 2 / (S ** 2).sum()
        rep.kv({"PC1 설명분산(%)": ev[0] * 100, "PC2(%)": ev[1] * 100, "PC3(%)": ev[2] * 100})
        load = Vt[:3].T * S[:3] / np.sqrt(len(X) - 1)
        r2 = pd.DataFrame({"sid": np.asarray(A.columns), "시군": [sigun.get(s, np.nan) for s in A.columns],
                           "PC1_R2": load[:, 0] ** 2, "PC1~3_R2": (load ** 2).sum(1)})
        rep.table(r2[["PC1_R2", "PC1~3_R2"]].describe().T.reset_index().rename(columns={"index": "지표"}),
                  "처리장 변동 중 공통 신호로 설명되는 비율", digits=3)
        rep.table(r2.sort_values("PC1_R2", ascending=False).head(15), "공통 신호를 가장 강하게 따르는 방류구", digits=3)
        rep.table(r2.sort_values("PC1_R2").head(15), "공통 신호와 가장 무관한 방류구(고유 요인 지배)", digits=3)
        rep.csv(r2, f"{v}_pca_r2.csv")
        pc1 = pd.DataFrame({"date": A.index, "PC1_score": U[:, 0] * S[0]})
        rep.csv(pc1, f"{v}_pc1_timeseries.csv")
        if v == "Q":
            rep.table(pc1.sort_values("PC1_score", ascending=False).head(20), "유량 공통 신호가 가장 큰 날(광역 강우일 후보)", digits=2)

        fig, ax = plt.subplots(figsize=(14, 4))
        dendrogram(Z, no_labels=True, ax=ax, color_threshold=Z[-n_cl + 1, 2] if n_cl > 1 else None)
        ax.set_title(f"{v} 일 편차 상관 기반 계층 군집")
        rep.fig(fig, f"{v}_dendrogram.png")

        order = np.argsort(lab)
        fig, ax = plt.subplots(figsize=(7, 6))
        im = ax.imshow(Rv[np.ix_(order, order)], cmap="RdBu_r", vmin=-1, vmax=1)
        fig.colorbar(im, ax=ax)
        ax.set_title(f"{v} 처리장 간 상관(군집 순 정렬)")
        ax.set_xticks([])
        ax.set_yticks([])
        rep.fig(fig, f"{v}_corr_heatmap.png")

    rep.save()


if __name__ == "__main__":
    main()
