# -*- coding: utf-8 -*-
"""
16. 배출 부하 기여도(파레토·지니) — 전체 사업장 대상
- 연간 부하량 = 일평균 부하 × 365(결측 보정). 완전한 연도(2024, 2025) 기준
- 소수 대형 시설이 도 전체 부하의 몇 %를 차지하나(상위 n개가 50%·80%), 지니계수
- 사업장 유형·시군별 부하와 유량가중 평균농도
- 2024→2025 부하 변화가 큰 시설
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import config as C
from common import Report, load_clean

LOADS = [f"{p}_load" for p in C.PARAMS]


def gini(x):
    x = np.sort(np.asarray(x, dtype=float))
    x = x[x >= 0]
    n = len(x)
    if n == 0 or x.sum() == 0:
        return np.nan
    return (2 * np.arange(1, n + 1) - n - 1).dot(x) / (n * x.sum())


def main():
    rep = Report("16_load_contribution", "16. 배출 부하 기여도",
                 "도 전체 방류 부하가 소수 시설에 얼마나 집중돼 있는지, 어떤 유형·지역이 큰지 본다. (부하 단위 가정: kg/일)")
    df = load_clean(types=None)
    df["year"] = df["date"].dt.year
    years = [y for y in sorted(df["year"].unique()) if df.loc[df["year"] == y, "month"].nunique() == 12]
    rep.kv({"완전 연도": years})

    site = (df[df["year"].isin(years)].groupby(["site", "site_type", "year"])
              .agg(**{f"{l}_일평균": (l, "mean") for l in LOADS}, Q일평균=("Q", "mean"),
                   유효일=("TN_load", "count"), 시군=("sigun", "first"))
              .reset_index())
    # 사업장 = 방류구 합. 방류구별 평균을 먼저 구해 더한다
    sid_mean = (df[df["year"].isin(years)].groupby(["site", "sid", "year"])[LOADS + ["Q"]].mean()
                  .groupby(["site", "year"]).sum().reset_index())
    site = site.drop(columns=[f"{l}_일평균" for l in LOADS] + ["Q일평균"]).merge(sid_mean, on=["site", "year"])
    for l in LOADS:
        site[f"{l.split('_')[0]}_연간톤"] = site[l] * 365 / 1000
    site["Q_연간백만m3"] = site["Q"] * 365 / 1e6
    rep.csv(site, "annual_load_by_site.csv")

    for y in years:
        rep.h(f"{y}년")
        s = site[site["year"] == y]
        tot = s.groupby("site_type")[[f"{p}_연간톤" for p in C.PARAMS] + ["Q_연간백만m3"]].sum()
        share = tot / tot.sum() * 100
        tot.columns = [c + "(합계)" for c in tot.columns]
        rep.table(tot.reset_index(), "유형별 연간 부하(톤/년)·유량(백만 m3/년)", digits=1)
        rep.table(share.reset_index(), "유형별 점유율(%)", digits=1)

        conc = []
        for tname, gg in s.groupby("site_type"):
            r = {"유형": tname}
            for p in C.PARAMS:
                r[f"{p}_유량가중평균"] = gg[f"{p}_load"].sum() / gg["Q"].sum() * 1000 if gg["Q"].sum() else np.nan
            conc.append(r)
        rep.table(pd.DataFrame(conc), "유형별 유량가중 평균농도(mg/L)", digits=3)

        par = []
        for p in C.PARAMS:
            v = s[f"{p}_연간톤"].dropna().sort_values(ascending=False)
            cs = v.cumsum() / v.sum()
            par.append({"항목": p, "시설수": len(v), "상위1개_pct": cs.iloc[0] * 100,
                        "상위5개_pct": cs.iloc[min(4, len(cs) - 1)] * 100,
                        "50%도달시설수": int((cs < 0.5).sum() + 1), "80%도달시설수": int((cs < 0.8).sum() + 1),
                        "지니": gini(v.values)})
        rep.table(pd.DataFrame(par), "부하 집중도", digits=2)
        rep.table(s.sort_values("TN_연간톤", ascending=False)[["site", "site_type", "시군", "Q_연간백만m3"] +
                                                               [f"{p}_연간톤" for p in C.PARAMS]].head(20),
                  "TN 연간 부하 상위 20 시설", digits=1)
        if s["시군"].notna().any():
            sg = s.groupby("시군")[[f"{p}_연간톤" for p in C.PARAMS] + ["Q_연간백만m3"]].sum().sort_values("TN_연간톤", ascending=False)
            rep.table(sg.reset_index(), "시군별 연간 부하", digits=1)

    if len(years) >= 2:
        rep.h(f"{years[0]}→{years[-1]} 변화")
        a = site[site["year"] == years[0]].set_index("site")
        b = site[site["year"] == years[-1]].set_index("site")
        common = a.index.intersection(b.index)
        ch = pd.DataFrame({"유형": a.loc[common, "site_type"], "시군": a.loc[common, "시군"]})
        for p in ["TN", "TP", "TOC"]:
            ch[f"{p}_변화톤"] = b.loc[common, f"{p}_연간톤"] - a.loc[common, f"{p}_연간톤"]
            ch[f"{p}_변화pct"] = (b.loc[common, f"{p}_연간톤"] / a.loc[common, f"{p}_연간톤"] - 1) * 100
        ch["Q_변화pct"] = (b.loc[common, "Q"] / a.loc[common, "Q"] - 1) * 100
        rep.csv(ch.reset_index(), "load_change_by_site.csv")
        rep.table(ch.sort_values("TN_변화톤", ascending=False).reset_index().head(15), "TN 부하 증가 상위 15", digits=1)
        rep.table(ch.sort_values("TN_변화톤").reset_index().head(15), "TN 부하 감소 상위 15", digits=1)
        rep.table(ch.groupby("유형")[["TN_변화톤", "TP_변화톤", "TOC_변화톤"]].sum().reset_index(), "유형별 순변화(톤)", digits=1)

    y = years[-1] if years else None
    if y:
        s = site[site["year"] == y]
        fig, axes = plt.subplots(1, 4, figsize=(15, 3.5))
        for ax, p in zip(axes, C.PARAMS):
            v = s[f"{p}_연간톤"].dropna().sort_values(ascending=False)
            ax.plot(np.arange(1, len(v) + 1), v.cumsum() / v.sum() * 100)
            ax.axhline(80, color="gray", ls="--", lw=0.7)
            ax.set_xscale("log")
            ax.set_title(f"{p} 누적 부하(%) {y}")
            ax.set_xlabel("시설 순위(로그)")
        rep.fig(fig, "pareto_curves.png")

    rep.save()


if __name__ == "__main__":
    main()
