# -*- coding: utf-8 -*-
"""
13. 처리장 유형화(특성 기반 군집 + PCA)
- 방류구별 '행동 특성' 지표를 만들고 표준화 → PCA → K-means(k=2~8, 실루엣으로 선택) + Ward 계층군집 비교
- 지표: 규모, 유량 변동·첨두, 항목별 수준·변동, 계절 진폭, 주말 효과, 자기상관(관성), C-Q 기울기, 결측률
- 결과: '어떤 종류의 처리장들이 있는가'에 대한 데이터 기반 분류(정책 대상 그룹화의 근거)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import config as C
from common import Report, load_clean, valid_sids, daily, anomaly, need


def features(g):
    f = {}
    q = daily(g, "Q")
    qv = q.dropna()
    f["log_Q중앙"] = np.log10(qv.median())
    f["Q_CV"] = qv.std() / qv.mean()
    f["Q_첨두"] = qv.quantile(0.99) / qv.median()
    for p in C.PARAMS:
        s = daily(g, p)
        sv = s.dropna()
        f[f"log_{p}중앙"] = np.log10(sv.median()) if sv.median() > 0 else np.nan
        f[f"{p}_CV"] = sv.std() / sv.mean() if sv.mean() else np.nan
        mm = s.groupby(s.index.month).mean()
        f[f"{p}_계절진폭"] = (mm.max() - mm.min()) / mm.mean() if mm.mean() else np.nan
        a = anomaly(s)
        f[f"{p}_자기상관1"] = a.autocorr(1)
    mmq = q.groupby(q.index.month).mean()
    f["Q_계절진폭"] = (mmq.max() - mmq.min()) / mmq.mean()
    r = q / q.rolling(31, center=True, min_periods=10).median()
    f["Q_주말/평일"] = r[r.index.dayofweek >= 5].median() / r[r.index.dayofweek < 5].median()
    qa_tn, qa_toc = anomaly(daily(g, "Q_TN")), anomaly(daily(g, "Q_TOC"))
    for p in ["SS", "TP", "TN"]:
        qa = qa_toc if p == "TN" else qa_tn
        d = pd.DataFrame({"q": qa, "c": anomaly(daily(g, p))}).dropna()
        f[f"{p}_CQ기울기"] = np.polyfit(d["q"], d["c"], 1)[0] if len(d) > 100 else np.nan
    f["결측률"] = daily(g, "TN").isna().mean()
    return f


def main():
    rep = Report("13_typology_clustering", "13. 처리장 유형화(특성 기반 군집)",
                 "여러 행동 특성을 한꺼번에 고려해 비슷한 처리장끼리 묶고, 각 그룹의 성격을 정의한다.")
    skl = need("sklearn", "scikit-learn")
    if skl is None:
        rep.p("scikit-learn 필요: pip install scikit-learn")
        rep.save()
        return
    from sklearn.preprocessing import StandardScaler
    from sklearn.decomposition import PCA
    from sklearn.cluster import KMeans, AgglomerativeClustering
    from sklearn.metrics import silhouette_score, adjusted_rand_score

    df = load_clean()
    df = df[df["sid"].isin(valid_sids(df, "TN"))]
    F = []
    for sid, g in df.groupby("sid"):
        f = features(g)
        f["sid"] = sid
        f["시군"] = g["sigun"].iloc[0]
        F.append(f)
    F = pd.DataFrame(F).set_index("sid")
    feat_cols = [c for c in F.columns if c != "시군"]
    X = F[feat_cols].replace([np.inf, -np.inf], np.nan)
    keep = X.notna().mean() > 0.9
    X = X.loc[:, keep]
    X = X.fillna(X.median()).clip(X.quantile(0.01), X.quantile(0.99), axis=1)
    Xs = StandardScaler().fit_transform(X)
    rep.csv(F.reset_index(), "features_by_sid.csv")
    rep.kv({"방류구 수": len(X), "사용 지표 수": X.shape[1], "사용 지표": ", ".join(X.columns)})

    rep.h("1. PCA")
    pca = PCA(n_components=min(6, X.shape[1]), random_state=C.RANDOM_STATE).fit(Xs)
    ev = pd.DataFrame({"주성분": [f"PC{i+1}" for i in range(pca.n_components_)],
                       "설명분산_pct": pca.explained_variance_ratio_ * 100,
                       "누적_pct": np.cumsum(pca.explained_variance_ratio_) * 100})
    rep.table(ev, digits=1)
    ld = pd.DataFrame(pca.components_[:3].T, index=X.columns, columns=["PC1", "PC2", "PC3"])
    rep.table(ld.reset_index().rename(columns={"index": "지표"}), "주성분 적재값(|값|이 클수록 그 축을 규정)", digits=2)

    rep.h("2. 군집 수 선택(K-means 실루엣)")
    sil = []
    for k in range(2, 9):
        lab = KMeans(n_clusters=k, n_init=20, random_state=C.RANDOM_STATE).fit_predict(Xs)
        sil.append({"k": k, "실루엣": silhouette_score(Xs, lab)})
    sil = pd.DataFrame(sil)
    rep.table(sil, digits=3)
    k_best = int(sil.sort_values("실루엣", ascending=False)["k"].iloc[0])
    k_use = max(k_best, 3)
    km = KMeans(n_clusters=k_use, n_init=50, random_state=C.RANDOM_STATE).fit(Xs)
    ward = AgglomerativeClustering(n_clusters=k_use, linkage="ward").fit_predict(Xs)
    rep.kv({"최적 k(실루엣)": k_best, "사용 k": k_use,
            "K-means vs Ward 일치도(ARI)": adjusted_rand_score(km.labels_, ward)})

    rep.h("3. 군집별 특성(원 단위 중앙값)")
    F2 = X.copy()
    F2["군집"] = km.labels_
    F2["시군"] = F.loc[X.index, "시군"]
    prof = F2.groupby("군집")[X.columns].median()
    prof.insert(0, "방류구수", F2.groupby("군집").size())
    rep.table(prof.reset_index(), digits=3)
    z = pd.DataFrame(Xs, index=X.index, columns=X.columns).groupby(km.labels_).mean()
    top = []
    for k, row in z.iterrows():
        s = row.sort_values()
        top.append({"군집": k, "특히 높은 지표": ", ".join(f"{i}(+{v:.1f})" for i, v in s.tail(3)[::-1].items()),
                    "특히 낮은 지표": ", ".join(f"{i}({v:.1f})" for i, v in s.head(3).items())})
    rep.table(pd.DataFrame(top), "군집을 규정하는 지표(표준화 평균)")
    mem = F2.reset_index()[["sid", "시군", "군집"]].sort_values(["군집", "sid"])
    rep.csv(mem, "cluster_membership.csv")
    for k, gg in mem.groupby("군집"):
        rep.p(f"- 군집 {k} ({len(gg)}개): " + ", ".join(gg["sid"].head(15)) + (" …" if len(gg) > 15 else ""))

    P = pca.transform(Xs)
    fig, ax = plt.subplots(figsize=(7, 6))
    sc = ax.scatter(P[:, 0], P[:, 1], c=km.labels_, cmap="tab10", s=18)
    for i, col in enumerate(X.columns):
        ax.arrow(0, 0, ld.loc[col, "PC1"] * 4, ld.loc[col, "PC2"] * 4, color="gray", alpha=0.5, head_width=0.05)
        ax.text(ld.loc[col, "PC1"] * 4.3, ld.loc[col, "PC2"] * 4.3, col, fontsize=6, color="dimgray")
    ax.set_xlabel(f"PC1 ({pca.explained_variance_ratio_[0]*100:.0f}%)")
    ax.set_ylabel(f"PC2 ({pca.explained_variance_ratio_[1]*100:.0f}%)")
    ax.set_title("처리장 유형화 PCA biplot")
    fig.colorbar(sc, ax=ax, label="군집")
    rep.fig(fig, "pca_biplot.png")

    rep.save()


if __name__ == "__main__":
    main()
