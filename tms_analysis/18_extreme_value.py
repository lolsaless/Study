# -*- coding: utf-8 -*-
"""
18. 극값 분석(GEV, GPD)
- 월 최대값(블록 최대) → GEV 적합 → 재현수준(1년, 5년 재현 농도)
- 상위 5% 초과분(POT) → GPD 적합 → 꼬리 두께(형상모수 ξ): 클수록 '드물지만 매우 큰' 사건이 나는 처리장
- 재현수준을 방류수 기준과 비교 → 기준 초과 위험의 확률적 표현
※ 월 최대값이 약 30개라 불확실성이 크다. 순위 비교 위주로 해석
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats

import config as C
from common import Report, load_clean, valid_sids, daily


def main():
    rep = Report("18_extreme_value", "18. 극값 분석(GEV·GPD)",
                 "처리장별로 '드물게 나타나는 높은 농도·유량'의 크기와 빈도를 확률로 표현한다.")
    df = load_clean()
    df = df[df["sid"].isin(valid_sids(df, "TN", min_days=600))]
    df["region"] = df["region"].fillna(C.DEFAULT_REGION)

    rows = []
    for sid, g in df.groupby("sid"):
        std = C.DISCHARGE_STANDARDS.get(g["region"].iloc[0], C.DISCHARGE_STANDARDS[C.DEFAULT_REGION])
        r = {"sid": sid, "시군": g["sigun"].iloc[0]}
        for v in C.PARAMS + ["Q"]:
            s = daily(g, v).dropna()
            if len(s) < 500:
                continue
            bm = s.resample("MS").max().dropna()
            if len(bm) >= 20:
                try:
                    c, loc, scale = stats.genextreme.fit(bm)
                    # 월 최대 기준: 1년 재현 = 1-1/12, 5년 = 1-1/60
                    r[f"{v}_GEV_ξ"] = -c
                    r[f"{v}_1년재현"] = stats.genextreme.ppf(1 - 1 / 12, c, loc, scale)
                    r[f"{v}_5년재현"] = stats.genextreme.ppf(1 - 1 / 60, c, loc, scale)
                except Exception:
                    pass
            u = s.quantile(0.95)
            exc = s[s > u] - u
            if len(exc) >= 30:
                try:
                    xi, _, sc = stats.genpareto.fit(exc, floc=0)
                    r[f"{v}_GPD_ξ"] = xi
                    r[f"{v}_p95"] = u
                except Exception:
                    pass
            if v in std and f"{v}_5년재현" in r:
                r[f"{v}_5년재현/기준"] = r[f"{v}_5년재현"] / std[v]
                r[f"{v}_1년재현/기준"] = r[f"{v}_1년재현"] / std[v]
        rows.append(r)
    t = pd.DataFrame(rows)
    rep.csv(t, "extreme_by_sid.csv")

    rep.h("1. 항목별 꼬리 특성(방류구 중앙값)")
    summ = []
    for v in C.PARAMS + ["Q"]:
        if f"{v}_GPD_ξ" not in t:
            continue
        summ.append({"항목": v, "GPD ξ 중앙": t[f"{v}_GPD_ξ"].median(), "ξ>0.2(두꺼운 꼬리) 비율%": (t[f"{v}_GPD_ξ"] > 0.2).mean() * 100,
                     "1년재현/기준 중앙": t.get(f"{v}_1년재현/기준", pd.Series(dtype=float)).median(),
                     "5년재현>기준 방류구": int((t.get(f"{v}_5년재현/기준", pd.Series(dtype=float)) > 1).sum())})
    rep.table(pd.DataFrame(summ), digits=3)
    rep.p("ξ>0: 상한 없이 가끔 매우 큰 값이 나오는 꼬리(충격형 처리장). ξ<0: 상한이 있는 꼬리(안정적 운전).")

    rep.h("2. 5년 재현 농도가 기준에 가까운/넘는 방류구")
    for v in ["TP", "TN", "SS", "TOC"]:
        c = f"{v}_5년재현/기준"
        if c in t:
            rep.table(t.sort_values(c, ascending=False)[["sid", "시군", f"{v}_1년재현", f"{v}_5년재현", c, f"{v}_GPD_ξ"]].head(15),
                      f"{v} 상위 15", digits=3)

    fig, axes = plt.subplots(1, 4, figsize=(15, 3.5))
    for ax, v in zip(axes, C.PARAMS):
        c = f"{v}_GPD_ξ"
        if c in t:
            ax.hist(t[c].dropna().clip(-1, 1.5), bins=30)
            ax.axvline(0, color="gray")
            ax.set_title(f"{v} GPD 형상모수 ξ")
    rep.fig(fig, "gpd_shape_hist.png")

    rep.save()


if __name__ == "__main__":
    main()
