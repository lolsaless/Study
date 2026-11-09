# -*- coding: utf-8 -*-
"""
23. 요일 지문(인위 배출 신호) — 계절 제거 편차의 요일 패턴, 진폭·검정(FDR), 강우 사건일·공휴일 제외
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats

import config as C
from core import Report, io, st
from core.events import station_events

REQUIRES = ["river_daily"]
LEVEL = "중급"
VARS = ["EC", "TOC", "TN", "TP", "Turb", "pH"]
DOW = ["월", "화", "수", "목", "금", "토", "일"]


def main():
    rep = Report("23_weekday_fingerprint", "23. 요일 지문: 하천에 남은 인위 배출 주기", level=LEVEL,
                 purpose="자연 현상에는 7일 주기가 없다. 하천 수질에 요일 패턴이 있다면 공장 가동·하수처리장 방류 같은 인위 배출의 흔적이다. "
                         "v2 에서 한강 5개 측정소로 확인한 방법(신천 TOC 진폭 29%)을 4대강 전체로 넓혔다.")
    d = io.load_daily(VARS + ["EC", "Turb"])
    rep.data_info(d)
    ev = station_events(d)[["station", "date", "wet"]]
    d = d.merge(ev, on=["station", "date"], how="left")
    hol = set(io.holidays())
    rows, prof = [], {}
    for b, stn, v, s in io.iter_series(d, VARS):
        a = st.deseason(s, v, win=29)
        g = d[d["station"] == stn].set_index("date")
        mask = (~g["wet"].reindex(a.index).fillna(False).astype(bool)) & (~a.index.isin(hol))
        a = a[mask].dropna()
        if len(a) < 200:
            continue
        grp = [a[a.index.dayofweek == k].values for k in range(7)]
        H, p = stats.kruskal(*grp)
        means = np.array([np.mean(x) for x in grp])
        eff = (np.exp(means - means.mean()) - 1) * 100 if v in C.LOG_VARS else means - means.mean()
        rows.append({"basin": b, "station": stn, "var": v, "n": len(a), "진폭": eff.max() - eff.min(),
                     "단위": "%" if v in C.LOG_VARS else C.VAR_INFO[v][1],
                     "최저요일": DOW[int(np.argmin(eff))], "최고요일": DOW[int(np.argmax(eff))], "p": p,
                     **{DOW[k]: eff[k] for k in range(7)}})
        prof[(stn, v)] = eff
    t = pd.DataFrame(rows)
    t["q"] = st.fdr(t["p"])
    rep.csv(t, "weekday_by_station.csv")
    rep.h("1. 요일 효과가 유의한 측정소(FDR q<0.01, 강우 사건일·공휴일 제외)")
    sig = t[(t["q"] < 0.01)].sort_values("진폭", ascending=False)
    rep.table(sig[["basin", "station", "var", "진폭", "단위", "최저요일", "최고요일", "q"] + DOW].head(30))
    summ = t.groupby("var").agg(측정소=("station", "size"), 유의=("q", lambda x: int((x < 0.01).sum())),
                                진폭중앙=("진폭", "median")).reindex(VARS)
    rep.table(summ, "항목별 유의 측정소 수", index=True)
    for v in ["TOC", "EC", "TN", "TP"]:
        x = sig[sig["var"] == v]
        if len(x):
            rep.finding(f"{v} 요일 지문 유의 {len(x)}곳 — 최대 " + ", ".join(f"{r.station}({r.basin}) {r.진폭:.0f}%[{r.최저요일}↓{r.최고요일}↑]" for r in x.head(3).itertuples()))
    rep.p("해석: 월·화 최저 → 주말 배출 감소가 1~2일 뒤 측정소에 도달(산업폐수·하수처리장 영향). "
          "상류 사업장과의 연결은 42번(TMS 연계)에서 직접 확인한다. 진폭은 계절을 뺀 로그 편차를 %로 바꾼 값.")
    if len(sig):
        fig, ax = plt.subplots(figsize=(8, 4.5))
        for r in sig.head(8).itertuples():
            ax.plot(DOW, prof[(r.station, r.var)], marker="o", label=f"{r.station} {r.var}")
        ax.axhline(0, color="gray", lw=0.6)
        ax.set_ylabel("계절 제거 편차(%)")
        ax.legend(fontsize=7, ncol=2)
        rep.fig(fig, "weekday_profiles.png", "요일 진폭 상위 8개 측정소×항목")
    rep.save()


if __name__ == "__main__":
    main()
