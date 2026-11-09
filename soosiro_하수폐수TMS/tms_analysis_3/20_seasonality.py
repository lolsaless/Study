# -*- coding: utf-8 -*-
"""
20. 계절성 — 월별 기후값, 계절성 강도(월 요인 설명력 R²), 연중 최고 시기(원형 통계·Rayleigh 검정)
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
LEVEL = "중급"
VARS = ["WT", "EC", "DO", "Turb", "TOC", "TN", "TP", "Chl_a"]


def main():
    rep = Report("20_seasonality", "20. 계절성: 강도와 시기", level=LEVEL,
                 purpose="항목별로 계절이 변동을 얼마나 설명하는지(R²), 연중 언제 최고가 되는지(원형 평균 시기·집중도)를 측정소마다 계산한다. "
                         "같은 항목이라도 최고 시기가 다른 측정소는 오염원·기작이 다르다는 신호다.")
    d = io.load_daily(VARS)
    rep.data_info(d)
    rows, clim = [], []
    for b, stn, v, s in io.iter_series(d, VARS):
        x = st.to_log(s, v).dropna()
        m = x.index.month
        grp = x.groupby(m)
        r2 = 1 - ((x - grp.transform("mean")) ** 2).sum() / ((x - x.mean()) ** 2).sum()
        mon = s.groupby(s.index.month).median()
        hi = s > s.quantile(0.75)            # 상위 25% 날의 연중 분포
        mdoy, R, p = st.circular_peak(s.index[hi.values].dayofyear)
        amp = (mon.max() / mon.min()) if v in C.LOG_VARS and mon.min() > 0 else mon.max() - mon.min()
        rows.append({"basin": b, "station": stn, "var": v, "계절성R2": r2, "최고월": int(mon.idxmax()), "최저월": int(mon.idxmin()),
                     "진폭(배 또는 차)": amp, "고농도 시기(일)": mdoy, "집중도R": R, "Rayleigh_p": p})
        clim.append(mon.rename(f"{stn}|{v}"))
    t = pd.DataFrame(rows)
    t["고농도 시기(월)"] = pd.to_datetime(t["고농도 시기(일)"].round().clip(1, 365).astype("Int64").astype(str), format="%j", errors="coerce").dt.month
    rep.csv(t, "seasonality_by_station.csv")
    cl = pd.concat(clim, axis=1).T
    cl.index.name = "station|var"
    rep.csv(cl.reset_index(), "monthly_climatology.csv")

    rep.h("1. 항목별 계절성 강도(측정소 중앙)")
    s = t.groupby("var").agg(측정소=("station", "size"), R2_중앙=("계절성R2", "median"),
                             R2_p10=("계절성R2", lambda x: x.quantile(0.1)), R2_p90=("계절성R2", lambda x: x.quantile(0.9)),
                             최고월_최빈=("최고월", lambda x: x.mode().iloc[0]), 집중도_중앙=("집중도R", "median")).reindex(VARS)
    rep.table(s, index=True)
    rep.p("R² = 월(1~12) 요인이 일 변동(로그)을 설명하는 비율. 수온은 거의 1, 사건성 항목(탁도·TP)은 낮다.")
    for v in ["TOC", "TP", "Chl_a", "EC"]:
        if v in s.index and pd.notna(s.loc[v, "R2_중앙"]):
            rep.finding(f"{v} 계절성 R² 중앙 {s.loc[v, 'R2_중앙']:.2f} (p10~p90 {s.loc[v, 'R2_p10']:.2f}~{s.loc[v, 'R2_p90']:.2f}), 최고월 최빈 {int(s.loc[v, '최고월_최빈'])}월")

    rep.h("2. 고농도 시기가 '다른' 측정소(같은 항목 안에서)")
    rep.p("상위 25% 날짜의 원형 평균 시기. 집중도 R 이 크고(≥0.5) Rayleigh p<0.05 이면 특정 계절에 몰린다. "
          "다수와 다른 시기에 몰리는 측정소는 별도 기작(예: 겨울 TP = 점오염·저유량 농축, 봄 Chl-a = 규조류)을 의심한다.")
    for v in ["TP", "Chl_a", "TOC", "TN"]:
        x = t[(t["var"] == v) & (t["집중도R"] >= 0.5) & (t["Rayleigh_p"] < 0.05)]
        if len(x) < 5:
            continue
        mode_m = x["고농도 시기(월)"].mode().iloc[0]
        circ = ((x["고농도 시기(월)"] - mode_m + 6) % 12 - 6).abs()
        odd = x[circ >= 3]
        rep.table(odd[["basin", "station", "고농도 시기(월)", "집중도R", "최고월", "계절성R2"]],
                  f"{v}: 다수({int(mode_m)}월 전후)와 3개월 이상 다른 측정소")
        if len(odd):
            rep.finding(f"{v} 고농도 시기가 다수({int(mode_m)}월)와 다른 측정소 {len(odd)}곳: {', '.join(odd['station'].head(6))}")

    fig, axes = plt.subplots(2, 4, figsize=(18, 9))
    order = d.drop_duplicates("station").sort_values(["basin", "station"])["station"].tolist()
    for ax, v in zip(axes.flat, VARS):
        z = cl[cl.index.str.endswith(f"|{v}")].copy()
        z.index = z.index.str.split("|").str[0]
        z = z.reindex([o for o in order if o in z.index])
        zz = np.log(z.clip(lower=1e-6)) if v in C.LOG_VARS else z
        zz = zz.sub(zz.mean(axis=1), axis=0).div(zz.std(axis=1).replace(0, np.nan), axis=0)
        ax.imshow(zz.values, aspect="auto", cmap="RdBu_r", vmin=-2, vmax=2)
        ax.set_yticks(range(len(zz)), zz.index, fontsize=4)
        ax.set_xticks(range(12), range(1, 13), fontsize=7)
        ax.set_title(v)
    fig.tight_layout()
    rep.fig(fig, "monthly_heatmaps.png", "측정소×월 표준화 월중앙값(빨강=그 측정소의 높은 달)")
    rep.save()


if __name__ == "__main__":
    main()
