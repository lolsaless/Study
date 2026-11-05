# -*- coding: utf-8 -*-
"""
11. 항목 간 상관과 농도-유량(C-Q) 관계
- 방류구 내부에서 일 편차(계절 제거) 간 Spearman 상관 → 전체 방류구의 중앙값 상관행렬
  예) SS↔TP 강한 양의 상관 = 인이 입자에 붙어 나감(여과·침전 성능 지표)
- C-Q 기울기 b: log C = a + b·log Q
  b<-0.1 희석형 / -0.1~0.1 안정형 / b>0.1 유출형  → 처리장 '강우 대응 유형' 예비 분류
- 부하-유량 탄력성 = 1 + b
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats

import config as C
from common import Report, load_clean, valid_sids, daily, anomaly

VARS = ["Q", "TOC", "SS", "TN", "TP", "pH"]


def cq_class(b):
    if np.isnan(b):
        return ""
    return "희석형" if b < -0.1 else ("유출형" if b > 0.1 else "안정형")


def main():
    rep = Report("11_param_correlation_cq", "11. 항목 간 상관과 농도-유량(C-Q) 관계",
                 "항목들이 함께 움직이는 방식과, 유량이 늘 때 농도가 희석되는지 오히려 높아지는지를 처리장별로 본다.")
    df = load_clean()
    df = df[df["sid"].isin(valid_sids(df, "TN"))]

    mats, rows = [], []
    for sid, g in df.groupby("sid"):
        A = pd.DataFrame({v: anomaly(daily(g, v), log=(v != "pH")) for v in VARS}).dropna()
        if len(A) < 100:
            continue
        cm = A.corr(method="spearman")
        mats.append(cm.values)
        r = {"sid": sid, "시군": g["sigun"].iloc[0], "Q중앙": g["Q"].median(), "n": len(A)}
        for i, a in enumerate(VARS):
            for b in VARS[i + 1:]:
                r[f"r_{a}_{b}"] = cm.loc[a, b]
        # C-Q 기울기: 원자료(로그) 회귀와 편차 기반 회귀 모두 계산
        # ※ 허위상관 방지: 항목 p의 C-Q에는 'p가 아닌 항목'으로 역산한 유량을 쓴다(TN→Q_TOC, 그 외→Q_TN)
        qa = {"TN": anomaly(daily(g, "Q_TOC")), "other": anomaly(daily(g, "Q_TN"))}
        qr = {"TN": daily(g, "Q_TOC"), "other": daily(g, "Q_TN")}
        for p in C.PARAMS:
            key = "TN" if p == "TN" else "other"
            raw = pd.DataFrame({"Q": qr[key], "C": daily(g, p)}).dropna()
            raw = raw[(raw > 0).all(axis=1)]
            if len(raw) > 100:
                sl = stats.linregress(np.log(raw["Q"]), np.log(raw["C"]))
                r[f"{p}_CQ_b_raw"] = sl.slope
                r[f"{p}_CQ_R2_raw"] = sl.rvalue ** 2
            AA = pd.DataFrame({"Q": qa[key], "C": anomaly(daily(g, p))}).dropna()
            if len(AA) < 100:
                continue
            sl2 = stats.linregress(AA["Q"], AA["C"])
            r[f"{p}_CQ_b"] = sl2.slope
            r[f"{p}_CQ_p"] = sl2.pvalue
            r[f"{p}_CQ유형"] = cq_class(sl2.slope)
            r[f"{p}_부하탄력성"] = 1 + sl2.slope
        rows.append(r)
    t = pd.DataFrame(rows)
    rep.csv(t, "corr_cq_by_sid.csv")

    rep.h("1. 방류구 내부 일 편차 상관(Spearman) — 방류구 중앙값")
    M = pd.DataFrame(np.nanmedian(np.stack(mats), axis=0), index=VARS, columns=VARS)
    rep.table(M.reset_index().rename(columns={"index": "항목"}), digits=2)
    rep.p("주의: 이 행렬의 Q는 주로 TN으로 역산한 유량이라 Q–TN 상관에는 허위 음의 상관이 섞일 수 있다. "
          "Q와 농도의 관계는 아래 C-Q(다른 항목으로 역산한 유량 사용) 결과로 판단한다.")
    pos = pd.DataFrame({c: [(t[c] > 0.3).mean() * 100, (t[c] < -0.3).mean() * 100]
                        for c in t.columns if c.startswith("r_")}, index=["r>0.3 비율%", "r<-0.3 비율%"]).T
    rep.table(pos.reset_index().rename(columns={"index": "쌍"}), "강한 상관을 보이는 방류구 비율", digits=1)

    rep.h("2. C-Q 유형(일 편차 기반 기울기)")
    cls = pd.DataFrame({p: t[f"{p}_CQ유형"].value_counts() for p in C.PARAMS}).fillna(0).astype(int)
    rep.table(cls.reset_index().rename(columns={"index": "유형"}))
    rep.table(t[[f"{p}_CQ_b" for p in C.PARAMS]].describe().T.reset_index().rename(columns={"index": "기울기"}), digits=3)
    rep.p("SS·TP가 '유출형'인 처리장은 유량이 늘 때 고형물이 빠져나가는 곳(침전·여과 한계) 후보. "
          "TN·TOC가 '희석형'이면 빗물 유입으로 묽어지는 곳.")
    for p in ["SS", "TP", "TN"]:
        rep.table(t.sort_values(f"{p}_CQ_b", ascending=False)[["sid", "시군", "Q중앙", f"{p}_CQ_b", f"{p}_CQ_p"]].head(12),
                  f"{p} 유출형 상위 12")

    fig, ax = plt.subplots(figsize=(5.5, 4.5))
    im = ax.imshow(M.values, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(VARS)))
    ax.set_xticklabels(VARS)
    ax.set_yticks(range(len(VARS)))
    ax.set_yticklabels(VARS)
    for i in range(len(VARS)):
        for j in range(len(VARS)):
            ax.text(j, i, f"{M.values[i, j]:.2f}", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax)
    ax.set_title("일 편차 Spearman 상관(방류구 중앙값)")
    rep.fig(fig, "corr_matrix_median.png")

    fig, axes = plt.subplots(1, 4, figsize=(15, 3.5))
    for ax, p in zip(axes, C.PARAMS):
        ax.hist(t[f"{p}_CQ_b"].dropna().clip(-2, 2), bins=40)
        ax.axvline(-0.1, color="gray", ls="--")
        ax.axvline(0.1, color="gray", ls="--")
        ax.set_title(f"{p} C-Q 기울기")
    rep.fig(fig, "cq_slope_hist.png")

    rep.save()


if __name__ == "__main__":
    main()
