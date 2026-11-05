# -*- coding: utf-8 -*-
"""
15. 자기상관과 주기(스펙트럼) 분석
- ACF(1, 7, 30일), 상관이 1/e 아래로 떨어지는 '기억 길이' → 공정 관성(체류시간·슬러지 반응 속도)
- 주기도(periodogram): 7일 주기(생활 패턴)와 연주기의 상대적 세기, 우세 주기
- PACF로 AR 차수 추정 → 예측모형 설계 참고
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import signal
from statsmodels.tsa.stattools import acf, pacf

import config as C
from common import Report, load_clean, valid_sids, daily

VARS = ["Q", "TOC", "SS", "TN", "TP"]


def band_power(f, P, lo, hi):
    m = (f >= lo) & (f <= hi)
    return P[m].sum()


def main():
    rep = Report("15_autocorr_spectral", "15. 자기상관과 주기 분석",
                 "처리장 수질이 얼마나 '오래 기억하는지'(관성)와 어떤 주기가 지배하는지 본다.")
    df = load_clean()
    df = df[df["sid"].isin(valid_sids(df, "TN", min_days=500))]

    rows = []
    for sid, g in df.groupby("sid"):
        r = {"sid": sid, "시군": g["sigun"].iloc[0]}
        for v in VARS:
            s = daily(g, v)
            x = np.log(s.where(s > 0)).interpolate(limit=3)
            x = x.loc[x.first_valid_index():x.last_valid_index()] if x.notna().any() else x
            if x.notna().sum() < 400 or x.isna().mean() > 0.1:
                continue
            x = x.interpolate().bfill().ffill()
            a = acf(x, nlags=60, fft=True)
            r[f"{v}_ACF1"], r[f"{v}_ACF7"], r[f"{v}_ACF30"] = a[1], a[7], a[30]
            below = np.where(a < 1 / np.e)[0]
            r[f"{v}_기억길이일"] = int(below[0]) if len(below) else 60
            pa = pacf(x, nlags=14, method="ywm")
            ci = 1.96 / np.sqrt(len(x))
            sig = np.where(np.abs(pa[1:]) > ci)[0]
            r[f"{v}_PACF유의최대차수"] = int(sig.max() + 1) if len(sig) else 0
            xd = signal.detrend(x.values)
            f, P = signal.periodogram(xd, fs=1.0)
            tot = P[f > 0].sum()
            r[f"{v}_7일대역비_pct"] = band_power(f, P, 1 / 7.5, 1 / 6.5) / tot * 100
            r[f"{v}_연주기대역비_pct"] = band_power(f, P, 1 / 500, 1 / 250) / tot * 100
            r[f"{v}_30일이상저주파_pct"] = band_power(f, P, 1e-9, 1 / 30) / tot * 100
            fm = f > 1 / 400
            r[f"{v}_우세주기일"] = 1 / f[fm][np.argmax(P[fm])] if fm.any() else np.nan
        rows.append(r)
    t = pd.DataFrame(rows)
    rep.csv(t, "acf_spectral_by_sid.csv")

    rep.h("1. 항목별 요약(방류구 중앙값)")
    summ = []
    for v in VARS:
        if f"{v}_ACF1" not in t:
            continue
        summ.append({"항목": v, "ACF1": t[f"{v}_ACF1"].median(), "ACF7": t[f"{v}_ACF7"].median(),
                     "ACF30": t[f"{v}_ACF30"].median(), "기억길이(일)": t[f"{v}_기억길이일"].median(),
                     "PACF 차수": t[f"{v}_PACF유의최대차수"].median(),
                     "7일 대역비%": t[f"{v}_7일대역비_pct"].median(),
                     "30일 이상 저주파%": t[f"{v}_30일이상저주파_pct"].median(),
                     "우세주기(일)_최빈": t[f"{v}_우세주기일"].round().mode().iloc[0] if t[f"{v}_우세주기일"].notna().any() else np.nan})
    rep.table(pd.DataFrame(summ), digits=2)
    rep.p("기억길이가 긴 항목 = 천천히 변하고 회복도 느림(예: TN—질산화 미생물). 짧은 항목 = 순간 충격형(예: SS). "
          "Q의 7일 대역비가 높을수록 생활하수 주간 패턴이 뚜렷.")

    rep.h("2. 관성이 큰/작은 방류구(TN 기억길이)")
    if "TN_기억길이일" in t:
        rep.table(t.sort_values("TN_기억길이일", ascending=False)[["sid", "시군", "TN_ACF1", "TN_ACF30", "TN_기억길이일"]].head(15))
        rep.table(t.sort_values("TN_기억길이일")[["sid", "시군", "TN_ACF1", "TN_ACF30", "TN_기억길이일"]].head(15))

    rep.h("3. 주간 패턴이 뚜렷한 방류구(Q 7일 대역비)")
    if "Q_7일대역비_pct" in t:
        rep.table(t.sort_values("Q_7일대역비_pct", ascending=False)[["sid", "시군", "Q_7일대역비_pct", "Q_우세주기일"]].head(15))

    fig, axes = plt.subplots(1, len(VARS), figsize=(16, 3.2))
    for ax, v in zip(axes, VARS):
        if f"{v}_기억길이일" in t:
            ax.hist(t[f"{v}_기억길이일"].dropna(), bins=30)
            ax.set_title(f"{v} 기억길이(일)")
    rep.fig(fig, "memory_length_hist.png")

    rep.save()


if __name__ == "__main__":
    main()
