# -*- coding: utf-8 -*-
"""
08. 장기 추세(계절 Mann-Kendall + Sen 기울기) 및 연도 간 같은 기간 비교
- 월 중앙값 시계열에 계절 Mann-Kendall 검정(계절성을 통제한 단조 추세)
- Sen 기울기(연간 변화율, 중앙값 대비 %), FDR 보정
- 같은 달끼리만 비교한 연도별 변화(2024 vs 2025 vs 2026 상반기)
※ 자료 기간이 약 2.5년이라 '추세'는 보조 지표로만 해석
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats

import config as C
from common import Report, load_clean, valid_sids, fdr, need

VARS = ["Q", "TOC", "SS", "TN", "TP"]


def seasonal_mk(monthly: pd.Series):
    """계절 Mann-Kendall(pymannkendall 있으면 사용, 없으면 간이 구현)"""
    pmk = need("pymannkendall")
    x = monthly.values.astype(float)
    if pmk is not None:
        r = pmk.seasonal_test(x, period=12)
        # [v2 수정] seasonal_test 의 Sen 기울기는 '같은 달끼리' 비교한 값이라 이미 '연당' 단위다(×12 하지 않음)
        return r.p, r.slope, r.trend
    # 간이: 같은 달끼리 Kendall S 합산
    months = monthly.index.month
    S, varS = 0.0, 0.0
    slopes = []
    for m in range(1, 13):
        y = monthly[months == m].dropna()
        n = len(y)
        if n < 2:
            continue
        v = y.values
        for i in range(n - 1):
            for j in range(i + 1, n):
                S += np.sign(v[j] - v[i])
                dy = (y.index[j].year - y.index[i].year)
                if dy:
                    slopes.append((v[j] - v[i]) / dy)
        varS += n * (n - 1) * (2 * n + 5) / 18
    if varS == 0:
        return np.nan, np.nan, "no trend"
    z = (S - np.sign(S)) / np.sqrt(varS)
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    slope = np.median(slopes) if slopes else np.nan
    return p, slope, ("increasing" if z > 0 else "decreasing") if p < 0.05 else "no trend"


def main():
    rep = Report("08_trend_mannkendall", "08. 장기 추세와 연도 간 비교",
                 "계절성을 통제한 상태에서 방류 농도·유량이 늘거나 줄고 있는 처리장이 있는지 본다.")
    df = load_clean()
    df = df[df["sid"].isin(valid_sids(df, "TN", min_days=600))]

    rows = []
    for sid, g in df.groupby("sid"):
        mon = g.set_index("date")[VARS].resample("MS").median()
        r = {"sid": sid, "시군": g["sigun"].iloc[0], "개월수": int(mon["TN"].notna().sum())}
        for v in VARS:
            s = mon[v]
            if s.notna().sum() < 24:
                continue
            p, slope, trend = seasonal_mk(s)
            r[f"{v}_p"] = p
            r[f"{v}_Sen연간"] = slope
            r[f"{v}_Sen연간_pct"] = slope / s.median() * 100 if s.median() else np.nan
        rows.append(r)
    t = pd.DataFrame(rows)
    for v in VARS:
        if f"{v}_p" in t:
            t[f"{v}_q"] = fdr(t[f"{v}_p"])
    rep.csv(t, "trend_by_sid.csv")

    rep.h("1. 유의한 추세가 있는 방류구 수(FDR q<0.05)")
    summ = []
    for v in VARS:
        if f"{v}_q" not in t:
            continue
        sig = t[f"{v}_q"] < 0.05
        summ.append({"항목": v, "분석 방류구": int(t[f"{v}_p"].notna().sum()),
                     "증가": int((sig & (t[f"{v}_Sen연간"] > 0)).sum()),
                     "감소": int((sig & (t[f"{v}_Sen연간"] < 0)).sum()),
                     "보정전 p<0.05": int((t[f"{v}_p"] < 0.05).sum()),
                     "Sen연간%_중앙": t[f"{v}_Sen연간_pct"].median()})
    rep.table(pd.DataFrame(summ))

    for v in ["TN", "TP", "Q"]:
        if f"{v}_Sen연간_pct" in t:
            d = t.dropna(subset=[f"{v}_p"]).sort_values(f"{v}_Sen연간_pct")
            rep.table(pd.concat([d.head(10), d.tail(10)])[["sid", "시군", f"{v}_Sen연간_pct", f"{v}_p", f"{v}_q"]],
                      f"{v}: 연간 변화율 하위 10 / 상위 10")

    rep.h("2. 같은 달끼리 연도 비교(하수 전체)")
    df["year"] = df["date"].dt.year
    months_all = df.groupby("year")["month"].unique()
    common = sorted(int(m) for m in set.intersection(*[set(m) for m in months_all]))
    sub = df[df["month"].isin(common)]
    yy = sub.groupby(["sid", "year"])[VARS].median().reset_index()
    ym = yy.groupby("year")[VARS].median().reset_index()
    rep.p(f"비교 대상 월: {common}")
    rep.table(ym, "연도별 방류구 중앙값의 중앙값")
    piv = yy.pivot(index="sid", columns="year", values="TN")
    yrs = sorted(piv.columns)
    if len(yrs) >= 2:
        d = (piv[yrs[-1]] / piv[yrs[0]] - 1) * 100
        rep.kv({f"TN {yrs[0]}→{yrs[-1]} 변화율 중앙값(%)": d.median(),
                "10% 이상 증가 방류구": int((d > 10).sum()), "10% 이상 감소 방류구": int((d < -10).sum())})

    fig, axes = plt.subplots(1, len(VARS), figsize=(16, 3.5))
    for ax, v in zip(axes, VARS):
        c = f"{v}_Sen연간_pct"
        if c in t:
            ax.hist(t[c].dropna().clip(-100, 100), bins=40)
            ax.axvline(0, color="gray")
            ax.set_title(f"{v} Sen 기울기(%/년)")
    rep.fig(fig, "sen_slope_hist.png")

    rep.save()


if __name__ == "__main__":
    main()
