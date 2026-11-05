# -*- coding: utf-8 -*-
"""
19. 선후행 관계(교차상관)와 그랜저 인과
- 유량 충격 뒤 며칠 후 농도가 반응하는가(교차상관 최대 지연, -7~+7일)
- 그랜저 인과(F-검정, 최대 3일): Q→SS, Q→TP, Q→TN, SS→TP, TOC→TN
  '예측에 도움이 되는가'를 뜻하며 물리적 인과를 증명하지는 않음
- 허위상관 방지: TN 관련 쌍에는 TOC로 역산한 유량, 그 외에는 TN으로 역산한 유량 사용
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from statsmodels.tsa.stattools import grangercausalitytests

import config as C
from common import Report, load_clean, valid_sids, daily, anomaly, fdr

PAIRS = [("Q", "SS"), ("Q", "TP"), ("Q", "TN"), ("Q", "TOC"), ("SS", "TP"), ("TOC", "TN"), ("TN", "TP")]
MAXLAG = 3


def xcorr(a, b, maxlag=7):
    out = {}
    for k in range(-maxlag, maxlag + 1):
        out[k] = a.corr(b.shift(-k))   # k>0: a가 b보다 k일 앞섬
    return pd.Series(out)


def main():
    rep = Report("19_lead_lag_granger", "19. 선후행 관계와 그랜저 인과",
                 "유량 충격과 수질 반응 사이의 시간 지연, 항목 간 예측적 선후 관계를 본다.")
    df = load_clean()
    df = df[df["sid"].isin(valid_sids(df, "TN"))]

    rows, xc_all = [], []
    for sid, g in df.groupby("sid"):
        A = {v: anomaly(daily(g, v)) for v in C.PARAMS}
        A["Q_forTN"] = anomaly(daily(g, "Q_TOC"))
        A["Q_other"] = anomaly(daily(g, "Q_TN"))
        A = pd.DataFrame(A)
        r = {"sid": sid, "시군": g["sigun"].iloc[0]}
        for a, b in PAIRS:
            ca = ("Q_forTN" if b == "TN" else "Q_other") if a == "Q" else a
            d = A[[ca, b]].dropna()
            if len(d) < 200:
                continue
            xc = xcorr(d[ca], d[b])
            k = int(xc.abs().idxmax())
            r[f"{a}→{b}_최대지연일"] = k
            r[f"{a}→{b}_최대상관"] = xc.loc[k]
            r[f"{a}→{b}_동시상관"] = xc.loc[0]
            xc_all.append(pd.DataFrame({"sid": sid, "쌍": f"{a}→{b}", "lag": xc.index, "r": xc.values}))
            try:
                res = grangercausalitytests(d[[b, ca]].values, maxlag=MAXLAG, verbose=False)
                r[f"{a}→{b}_G_p"] = min(res[l][0]["ssr_ftest"][1] for l in range(1, MAXLAG + 1))
                rev = grangercausalitytests(d[[ca, b]].values, maxlag=MAXLAG, verbose=False)
                r[f"{b}→{a}_G_p(역)"] = min(rev[l][0]["ssr_ftest"][1] for l in range(1, MAXLAG + 1))
            except Exception:
                pass
        rows.append(r)
    t = pd.DataFrame(rows)
    for c in [c for c in t.columns if "_G_p" in c]:
        t[c.replace("_G_p", "_G_q")] = fdr(t[c])
    rep.csv(t, "leadlag_granger_by_sid.csv")
    xc = pd.concat(xc_all) if xc_all else pd.DataFrame()
    if not xc.empty:
        rep.csv(xc, "xcorr_long.csv")

    rep.h("1. 쌍별 요약")
    summ = []
    for a, b in PAIRS:
        k = f"{a}→{b}"
        if f"{k}_최대지연일" not in t:
            continue
        summ.append({"쌍": k, "방류구": int(t[f"{k}_최대지연일"].notna().sum()),
                     "동시상관_중앙": t[f"{k}_동시상관"].median(),
                     "최대상관_중앙": t[f"{k}_최대상관"].median(),
                     "최대지연일_최빈": t[f"{k}_최대지연일"].mode().iloc[0],
                     "그랜저 유의(q<0.05)%": (t.get(f"{k}_G_q", pd.Series(dtype=float)) < 0.05).mean() * 100,
                     "역방향 유의(q<0.05)%": (t.get(f"{b}→{a}_G_q(역)", pd.Series(dtype=float)) < 0.05).mean() * 100})
    rep.table(pd.DataFrame(summ), digits=3)
    rep.p("최대지연일이 +1~+3이면 앞 항목이 그만큼 먼저 움직임. Q→SS·TP가 유의하고 역방향은 약하면 '유량 충격 → 고형물·인 유출' 구조.")

    if not xc.empty:
        rep.h("2. 지연별 평균 교차상관(방류구 중앙값)")
        piv = xc.groupby(["쌍", "lag"])["r"].median().unstack("lag")
        rep.table(piv.reset_index(), digits=3)
        fig, ax = plt.subplots(figsize=(8, 4))
        for k, row in piv.iterrows():
            ax.plot(row.index, row.values, marker=".", label=k)
        ax.axvline(0, color="gray", lw=0.6)
        ax.set_xlabel("지연(일) — 양수: 앞 항목이 선행")
        ax.set_ylabel("교차상관(중앙값)")
        ax.legend(fontsize=7)
        rep.fig(fig, "xcorr_median.png")

    rep.save()


if __name__ == "__main__":
    main()
