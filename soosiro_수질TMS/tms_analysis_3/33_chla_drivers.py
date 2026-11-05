# -*- coding: utf-8 -*-
"""
33. 조류(Chl-a) 결정 요인 — 기계학습(그래디언트 부스팅 + 시간 블록 교차검증 + 순열 중요도 + 부분의존) & 분위회귀(상한 반응)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import config as C
from core import Report, io

REQUIRES = ["river_daily"]
LEVEL = "심화"
FEATS = ["WT", "WT_7d", "log_TP", "log_TP_7d", "log_TN", "log_EC", "log_Turb_3dmax", "doy_sin", "doy_cos"]
NAMES = {"WT": "수온", "WT_7d": "수온 7일평균", "log_TP": "TP", "log_TP_7d": "TP 7일평균", "log_TN": "TN",
         "log_EC": "EC", "log_Turb_3dmax": "최근3일 최대탁도", "doy_sin": "계절(sin)", "doy_cos": "계절(cos)"}


def build(d):
    out = []
    for stn, g in d.groupby("station"):
        g = g.set_index("date").sort_index().asfreq("D")
        f = pd.DataFrame(index=g.index)
        f["y"] = np.log(g["Chl_a"].clip(lower=0.1))
        f["WT"] = g["WT"]
        f["WT_7d"] = g["WT"].rolling(7, min_periods=4).mean()
        for v in ["TP", "TN", "EC"]:
            f[f"log_{v}"] = np.log(g[v].clip(lower=1e-3))
        f["log_TP_7d"] = f["log_TP"].rolling(7, min_periods=4).mean()
        f["log_Turb_3dmax"] = np.log(g["Turb"].clip(lower=0.1).rolling(3, min_periods=1).max())
        f["doy_sin"], f["doy_cos"] = np.sin(2 * np.pi * f.index.dayofyear / 365.25), np.cos(2 * np.pi * f.index.dayofyear / 365.25)
        f["station"], f["basin"] = stn, g["basin"].dropna().iloc[0] if g["basin"].notna().any() else None
        f["block"] = f.index.to_period("M").astype(str)
        out.append(f.reset_index())
    return pd.concat(out, ignore_index=True)


def main():
    rep = Report("33_chla_drivers", "33. 조류(Chl-a)를 움직이는 요인", level=LEVEL,
                 purpose="수온·영양염·탁도·계절 중 무엇이 Chl-a 를 가장 잘 설명하는지 수계별로 비선형 모형으로 평가하고(순열 중요도), "
                         "TP 가 높을 때 Chl-a 가 '최대 어디까지' 오를 수 있는지 분위회귀(90% 분위)로 추정한다.")
    try:
        from sklearn.ensemble import HistGradientBoostingRegressor
        from sklearn.inspection import permutation_importance, partial_dependence
        from sklearn.model_selection import GroupKFold
    except ImportError:
        return rep.wait("scikit-learn 이 필요하다: pip install scikit-learn")
    d = io.load_daily(["WT", "TP", "TN", "EC", "Turb", "Chl_a"])
    rep.data_info(d)
    X = build(d)
    imp_rows, perf_rows, pd_curves = [], [], {}
    for mode, b in [(m_, b_) for m_ in ["통합", "측정소내"] for b_ in C.BASINS]:
        x = X[(X["basin"] == b)].dropna(subset=["y", "WT", "log_TP"])
        x = x[x["station"].map(x["station"].value_counts()) > 150]
        if len(x) < 800:
            continue
        if mode == "측정소내":       # 측정소 평균을 빼서 '측정소 간 차이'를 없애고 시간 변동의 요인만 본다
            cols = ["y"] + [f_ for f_ in FEATS if not f_.startswith("doy")]
            x = x.copy()
            x[cols] = x[cols] - x.groupby("station")[cols].transform("mean")
        gkf = GroupKFold(n_splits=5)
        r2s, imps = [], []
        for tr, te in gkf.split(x, groups=x["block"]):          # 월 단위 블록 → 시간 자기상관 누설 방지
            m = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
                                              random_state=C.RANDOM_STATE).fit(x.iloc[tr][FEATS], x.iloc[tr]["y"])
            pred = m.predict(x.iloc[te][FEATS])
            yt = x.iloc[te]["y"]
            r2s.append(1 - ((yt - pred) ** 2).sum() / ((yt - yt.mean()) ** 2).sum())
            pi = permutation_importance(m, x.iloc[te][FEATS], yt, n_repeats=5, random_state=C.RANDOM_STATE)
            imps.append(pi.importances_mean)
        imp = pd.Series(np.mean(imps, axis=0), index=FEATS)
        perf_rows.append({"모형": mode, "수계": b, "자료(일)": len(x), "측정소": x["station"].nunique(), "검증 R²(월 블록 CV)": np.mean(r2s)})
        for f_, v in imp.items():
            imp_rows.append({"모형": mode, "수계": b, "요인": NAMES[f_], "순열중요도(R² 감소)": v})
        if mode != "통합":
            continue
        m = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=15, random_state=C.RANDOM_STATE).fit(x[FEATS], x["y"])
        for f_ in ["WT", "log_TP"]:
            r = partial_dependence(m, x[FEATS], [FEATS.index(f_)], grid_resolution=30)
            grid = r["grid_values"][0] if "grid_values" in r else r["values"][0]
            pd_curves[(b, f_)] = (grid, r["average"][0])
    perf, imp = pd.DataFrame(perf_rows), pd.DataFrame(imp_rows)
    rep.h("1. 모형 설명력")
    rep.table(perf)
    rep.p("통합 = 측정소 간 차이 + 시간 변동을 함께 설명(EC 같은 '측정소 성격' 변수가 강하게 나옴). "
          "측정소내 = 측정소 평균을 뺀 '같은 측정소에서 날마다 달라지는 이유'.")
    rep.h("2. 요인 중요도(순열 중요도: 그 요인을 섞으면 R² 가 얼마나 떨어지나)")
    rep.csv(imp, "importance.csv")
    for mode in ["통합", "측정소내"]:
        piv = imp[imp["모형"] == mode].pivot_table(index="요인", columns="수계", values="순열중요도(R² 감소)").round(3)
        if piv.empty:
            continue
        piv = piv.loc[piv.mean(axis=1).sort_values(ascending=False).index]
        rep.table(piv, f"{mode} 모형", index=True)
        pf = perf[perf["모형"] == mode].set_index("수계")
        for b in piv.columns:
            top = piv[b].sort_values(ascending=False).index[:2]
            rep.finding(f"{b} Chl-a [{mode}] 주요 요인: {top[0]} > {top[1]} (월 블록 교차검증 R²={pf.loc[b, '검증 R²(월 블록 CV)']:.2f})")

    rep.h("3. 분위회귀: log Chl-a ~ log TP + 수온 (50%·90% 분위)")
    try:
        import statsmodels.formula.api as smf
        rows = []
        for b in C.BASINS:
            x = X[(X["basin"] == b)].dropna(subset=["y", "WT", "log_TP"])
            if len(x) < 500:
                continue
            for q in [0.5, 0.9]:
                f = smf.quantreg("y ~ log_TP + WT", x).fit(q=q, max_iter=5000)
                rows.append({"수계": b, "분위": q, "TP 탄력성": f.params["log_TP"], "TP 95%CI": f"{f.conf_int().loc['log_TP', 0]:.2f}~{f.conf_int().loc['log_TP', 1]:.2f}",
                             "수온 1℃당 %": (np.exp(f.params["WT"]) - 1) * 100, "n": len(x)})
        qr = pd.DataFrame(rows)
        rep.table(qr)
        rep.p("TP 탄력성 = TP 가 1% 오를 때 Chl-a 가 몇 % 오르나. 90% 분위의 탄력성이 50% 보다 크면, 영양염이 '평소'보다 '최악의 날'을 더 좌우한다 "
              "→ 인 저감이 고농도 조류 억제에 더 효과적이라는 근거.")
        for b, g in qr.groupby("수계"):
            if len(g) == 2:
                e50, e90 = g.set_index("분위").loc[0.5, "TP 탄력성"], g.set_index("분위").loc[0.9, "TP 탄력성"]
                rep.finding(f"{b} Chl-a 의 TP 탄력성: 중앙 {e50:.2f} → 상위10% {e90:.2f} " + ("(고농도일수록 인 영향 큼)" if e90 > e50 else "(고농도에서 인 영향 작음 = 다른 제한 요인)"))
    except ImportError:
        rep.p("statsmodels 가 없어 분위회귀를 생략했다.")
    if pd_curves:
        fig, axes = plt.subplots(1, 2, figsize=(11, 4))
        for (b, f_), (gx, gy) in pd_curves.items():
            ax = axes[0] if f_ == "WT" else axes[1]
            ax.plot(np.exp(gx) if f_ == "log_TP" else gx, np.exp(gy), label=b)
        axes[0].set_xlabel("수온(℃)")
        axes[1].set_xlabel("TP(mg/L)")
        axes[1].set_xscale("log")
        for ax in axes:
            ax.set_ylabel("Chl-a 부분의존(mg/㎥)")
            ax.legend()
        rep.fig(fig, "partial_dependence.png", "다른 요인을 평균으로 둘 때 수온·TP 에 따른 Chl-a 반응(임계점 확인)")
    rep.save()


if __name__ == "__main__":
    main()
