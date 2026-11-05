# -*- coding: utf-8 -*-
"""
38. 측정망 정보 중복도 — 한 측정소의 일 변동을 같은 수계 다른 측정소들로 재현(릿지 회귀, 시간 순 검증 R²) → 대체 가능성·고유 정보 순위
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
VARS = ["EC", "TOC", "WT", "Turb", "TP"]


def ridge_r2(X, y, alpha=1.0):
    cut = int(len(y) * 0.6)
    Xtr, Xte, ytr, yte = X[:cut], X[cut:], y[:cut], y[cut:]
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
    A = (Xtr - mu) / sd
    beta = np.linalg.solve(A.T @ A + alpha * len(A) * np.eye(A.shape[1]), A.T @ (ytr - ytr.mean()))
    pred = ((Xte - mu) / sd) @ beta + ytr.mean()
    return 1 - ((yte - pred) ** 2).sum() / ((yte - yte.mean()) ** 2).sum(), np.abs(beta)


def main():
    rep = Report("38_network_redundancy", "38. 측정망 정보 중복도(대체 가능성)", level=LEVEL,
                 purpose="한 측정소의 '계절을 뺀 일 변동'을 같은 수계 다른 측정소 자료로 얼마나 재현할 수 있는지 본다. "
                         "재현도(R²)가 높으면 정보가 겹치고, 낮으면 그 측정소만 주는 고유 정보다 → 측정망 운영·증설 우선순위 근거(v2 에 없던 분석).")
    d = io.load_daily(VARS)
    rep.data_info(d)
    rows = []
    for b in C.BASINS:
        for v in VARS:
            w = io.wide(d[d["basin"] == b], v)
            a = pd.DataFrame({c: st.deseason(w[c], v) for c in w.columns})
            a = a.loc[:, a.notna().mean() > 0.6]
            if a.shape[1] < 4:
                continue
            for target in a.columns:
                others = [c for c in a.columns if c != target]
                x = a[[target] + others].dropna(subset=[target])
                x[others] = x[others].fillna(x[others].median())
                if len(x) < 300:
                    continue
                r2, coef = ridge_r2(x[others].values, x[target].values)
                top = [others[i] for i in np.argsort(coef)[::-1][:2]]
                rows.append({"basin": b, "var": v, "station": target, "재현 R²": r2, "가장 닮은 측정소": ", ".join(top), "예측자 수": len(others)})
    t = pd.DataFrame(rows)
    rep.csv(t, "redundancy.csv")
    rep.h("1. 항목별 재현도 분포")
    rep.table(t.groupby(["var", "basin"])["재현 R²"].median().unstack().round(2), index=True)
    piv = t.pivot_table(index=["basin", "station"], columns="var", values="재현 R²")
    piv["평균"] = piv.mean(axis=1)
    piv = piv.sort_values("평균")
    rep.h("2. 고유 정보가 가장 큰 측정소(재현도 낮음) / 중복이 큰 측정소")
    rep.table(piv.head(12).round(2), "고유 정보 상위 12(대체 불가 — 유지·우선 관리)", index=True)
    rep.table(piv.tail(8).round(2), "중복 상위 8(다른 측정소로 상당 부분 재현)", index=True)
    rep.finding(f"고유 정보가 큰 측정소: {', '.join(s for _, s in piv.head(5).index)} (계절 제거 변동 재현 R² 평균 {piv['평균'].head(5).mean():.2f})")
    rep.finding(f"중복이 큰 측정소: {', '.join(s for _, s in piv.tail(3).index)} (R² 평균 {piv['평균'].tail(3).mean():.2f}) — 항목 축소·이동 검토 후보(단, 경보 목적은 별도 판단)")
    rep.p("주의: 재현도는 '날마다의 변동'에 대한 것이다. 수준(농도 값 자체)과 사고 감시 목적은 다르므로 이 결과만으로 측정소를 없애면 안 된다.")
    fig, ax = plt.subplots(figsize=(8, max(5, len(piv) * 0.15)))
    im = ax.imshow(piv[VARS if set(VARS) <= set(piv.columns) else piv.columns[:-1]].values, aspect="auto", cmap="viridis", vmin=0, vmax=1)
    ax.set_yticks(range(len(piv)), [s for _, s in piv.index], fontsize=5)
    ax.set_xticks(range(len(piv.columns) - 1), piv.columns[:-1])
    fig.colorbar(im, label="재현 R²")
    rep.fig(fig, "redundancy_heatmap.png")
    rep.save()


if __name__ == "__main__":
    main()
