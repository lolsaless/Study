# -*- coding: utf-8 -*-
"""
31. 측정소 유형화 — 수준·변동·계절·일주기·요일 특성 → 표준화 → PCA + 군집(K-means, 실루엣으로 k 선택) + Ward 계통도
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
LEVEL = "심화"
VARS = ["WT", "EC", "DO", "Turb", "TOC", "TN", "TP", "Chl_a"]


def features(d):
    rows = []
    for (b, stn), g in d.groupby(["basin", "station"]):
        r = {"basin": b, "station": stn}
        for v in ["EC", "TOC", "TN", "TP", "Chl_a", "Turb"]:
            x = g[v].dropna()
            if len(x) > 200:
                r[f"log_{v}"] = np.log(x.clip(lower=1e-4)).median()
                r[f"CV_{v}"] = x.std() / x.mean()
        x = g.dropna(subset=["WT"])
        if len(x) > 200:
            r["수온_여름"] = x.loc[x["month"].between(7, 8), "WT"].median()
            r["수온_진폭"] = x.groupby("month")["WT"].median().agg(lambda m: m.max() - m.min())
        if g["DO_max"].notna().sum() > 200:
            r["DO일교차"] = (g["DO_max"] - g["DO_min"]).median()
            r["DO포화_여름"] = g.loc[g["month"].between(6, 9), "DO_sat"].median()
        x = g.dropna(subset=["Chl_a"])
        if len(x) > 200:
            mon = x.groupby("month")["Chl_a"].median()
            sm, wn = mon.reindex([7, 8, 9]).mean(), mon.reindex([12, 1, 2]).mean()
            r["Chl_a_여름/겨울"] = np.log(sm / max(wn, 0.1)) if pd.notna(sm) and pd.notna(wn) else np.nan
        rows.append(r)
    return pd.DataFrame(rows)


def main():
    rep = Report("31_typology", "31. 측정소 유형화(PCA·군집)", level=LEVEL,
                 purpose="77개 측정소를 '수질 성격'으로 묶는다. 같은 유형은 같은 관리 전략·같은 모형을 적용할 수 있고, "
                         "유형에서 벗어난 측정소는 따로 볼 가치가 있다.")
    d = io.load_daily(VARS, minmax=True)
    rep.data_info(d)
    F = features(d).set_index(["basin", "station"])
    F = F.loc[:, F.notna().mean() >= 0.65]
    F = F[F.notna().mean(axis=1) >= 0.7]
    X = F.fillna(F.median())
    Z = (X - X.mean()) / X.std()
    rep.p(f"특성 {Z.shape[1]}개 × 측정소 {Z.shape[0]}곳 (결측은 전체 중앙값으로 채움): {', '.join(Z.columns)}")
    U, S, Vt = np.linalg.svd(Z.values, full_matrices=False)
    expl = S ** 2 / (S ** 2).sum()
    pcs = pd.DataFrame(U[:, :3] * S[:3], index=Z.index, columns=["PC1", "PC2", "PC3"])
    load = pd.DataFrame(Vt[:3].T, index=Z.columns, columns=["PC1", "PC2", "PC3"])
    rep.h("1. 주성분")
    rep.kv({f"PC{i + 1} 설명비율": expl[i] for i in range(3)})
    rep.table(load.round(2).sort_values("PC1"), "적재량", index=True)
    try:
        from sklearn.cluster import KMeans
        from sklearn.metrics import silhouette_score
        best = None
        for k in range(2, 7):
            km = KMeans(k, n_init=20, random_state=C.RANDOM_STATE).fit(Z.values)
            sc = silhouette_score(Z.values, km.labels_)
            if best is None or sc > best[0]:
                best = (sc, k, km.labels_)
        sil, k, lab = best
    except ImportError:
        from scipy.cluster.hierarchy import fcluster, linkage
        k, sil = 4, np.nan
        lab = fcluster(linkage(Z.values, "ward"), k, "maxclust") - 1
    F["유형"] = lab
    prof = X.assign(유형=lab).groupby("유형").median()
    prof.insert(0, "측정소수", F.groupby("유형").size())
    rep.h(f"2. 군집 결과(k={k}, 실루엣 {sil:.2f})")
    rep.table(prof.round(2), "유형별 특성 중앙값", index=True)
    zs = Z.assign(유형=lab).groupby("유형").mean()
    names = {}
    for c, r in zs.iterrows():
        hi = r.sort_values(ascending=False).index[:2]
        lo = r.sort_values().index[:1]
        names[c] = f"유형{c}: {'·'.join(hi)} 높음 / {lo[0]} 낮음"
    members = F.reset_index().groupby("유형").apply(lambda g: ", ".join(f"{s}({b[:2]})" for b, s in zip(g["basin"], g["station"])))
    rep.table(pd.DataFrame({"설명": pd.Series(names), "측정소": members}), "유형 설명과 소속", index=True)
    for c in names:
        rep.finding(f"{names[c]} — {int((lab == c).sum())}곳")
    out = F.reset_index().merge(pcs.reset_index(), on=["basin", "station"])
    rep.csv(out, "typology.csv")
    out.to_csv(C.WORK_DIR / "station_types.csv", index=False, encoding="utf-8-sig")
    cross = pd.crosstab(out["유형"], out["basin"])
    rep.table(cross, "유형 × 수계", index=True)

    fig, ax = plt.subplots(figsize=(8, 6))
    for c in sorted(set(lab)):
        m = lab == c
        ax.scatter(pcs.loc[m, "PC1"], pcs.loc[m, "PC2"], label=f"유형{c}", s=25)
    for (b, s_), r in pcs.iterrows():
        ax.annotate(s_, (r["PC1"], r["PC2"]), fontsize=6)
    for f_, r in load.iterrows():
        ax.arrow(0, 0, r["PC1"] * 3, r["PC2"] * 3, color="gray", alpha=0.5, head_width=0.05)
        ax.annotate(f_, (r["PC1"] * 3.2, r["PC2"] * 3.2), fontsize=6, color="gray")
    ax.set_xlabel(f"PC1 ({expl[0]:.0%})")
    ax.set_ylabel(f"PC2 ({expl[1]:.0%})")
    ax.legend()
    rep.fig(fig, "pca_biplot.png", "측정소 PCA 바이플롯(색=유형)")
    try:
        from scipy.cluster.hierarchy import dendrogram, linkage
        fig, ax = plt.subplots(figsize=(14, 4))
        dendrogram(linkage(Z.values, "ward"), labels=[s for _, s in Z.index], leaf_font_size=6, ax=ax)
        rep.fig(fig, "ward_dendrogram.png", "Ward 계통도")
    except Exception:  # noqa: BLE001
        pass
    rep.save()


if __name__ == "__main__":
    main()
