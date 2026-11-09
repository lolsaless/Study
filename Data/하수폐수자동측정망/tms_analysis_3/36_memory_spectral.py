# -*- coding: utf-8 -*-
"""
36. 시계열 기억·주기 — 자기상관 e-folding 시간, DFA 지수(장기기억), 주기 스펙트럼(7일·연주기) 세기
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
VARS = ["WT", "EC", "DO", "TOC", "TN", "TP", "Chl_a", "Turb"]


def weekly_power(a):
    x = a.interpolate(limit=3).dropna()
    if len(x) < 200:
        return np.nan
    x = x - x.mean()
    f = np.fft.rfftfreq(len(x), 1)
    p = np.abs(np.fft.rfft(x.values)) ** 2
    near = (f > 1 / 7.5) & (f < 1 / 6.6)
    bg = (f > 1 / 12) & (f < 1 / 4) & ~near
    return p[near].mean() / p[bg].mean() if bg.any() and near.any() else np.nan


def main():
    rep = Report("36_memory_spectral", "36. 시계열 기억 길이와 주기", level=LEVEL,
                 purpose="계절을 뺀 편차가 며칠이나 이어지는지(관성), 우연한 출렁임인지 장기기억인지(DFA), 7일 주기가 배경보다 강한지 본다. "
                         "기억이 길면 예측이 쉽고(37번), 7일 주기가 강하면 인위 배출 영향(23번)이다. 호소와 하천의 차이도 드러난다.")
    d = io.load_daily(VARS)
    rep.data_info(d)
    rows = []
    for b, stn, v, s in io.iter_series(d, VARS):
        a = st.deseason(s, v)
        rows.append({"basin": b, "station": stn, "var": v, "waterbody": d.loc[d["station"] == stn, "waterbody"].iloc[0],
                     "lag1 자기상관": a.autocorr(1), "e-folding(일)": st.efold_time(a, 60), "DFA α": st.dfa_hurst(a),
                     "7일주기 세기": weekly_power(a)})
    t = pd.DataFrame(rows)
    rep.csv(t, "memory_by_station.csv")
    rep.h("1. 항목별 기억 길이")
    rep.table(t.groupby("var")[["lag1 자기상관", "e-folding(일)", "DFA α", "7일주기 세기"]].median().reindex(VARS).round(2), index=True)
    rep.p("e-folding = 자기상관이 1/e 밑으로 떨어지는 날 수. DFA α: 0.5 무작위, 0.5~1 장기기억, >1 비정상(추세·계단).")
    rep.h("2. 호소 vs 하천")
    hw = t.groupby(["var", "waterbody"])["e-folding(일)"].median().unstack()
    rep.table(hw.round(1), index=True)
    if "호소" in hw and "하천" in hw:
        v_ = (hw["호소"] / hw["하천"]).dropna()
        r_ = v_.median()
        rep.finding(f"계절 제거 편차의 기억 길이: 호소가 하천의 {r_:.1f}배(항목 중앙) — "
                    + ("호소는 한 번 나빠지면 오래 간다" if r_ >= 1.3 else "31일 창으로 계절을 뺀 단기 변동에서는 호소·하천 차이가 작다"))
    w7 = t[t["7일주기 세기"] > 3].sort_values("7일주기 세기", ascending=False)
    rep.table(w7.head(15)[["basin", "station", "var", "7일주기 세기"]], "7일 주기가 배경의 3배 이상인 측정소×항목")
    if len(w7):
        rep.finding(f"7일 주기 스펙트럼이 배경의 3배 이상: {len(w7)}건 — " + ", ".join(f"{a} {b}" for a, b in zip(w7['station'].head(5), w7['var'].head(5))))
    lm = t[t["DFA α"] > 1.0]
    if len(lm):
        rep.finding(f"DFA α>1(계단·추세성 변동) 측정소×항목 {len(lm)}건 — 25번 변화점과 대조 권장")
    rep.finding(f"DFA α 중앙 {t['DFA α'].median():.2f} — 계절 제거 후에도 장기기억(0.5<α<1)이 있어 '독립 표본' 가정 검정은 유의성을 과대평가한다(블록 부트스트랩·측정소 단위 검정 사용 이유)")
    fig, ax = plt.subplots(figsize=(7, 4))
    for wb, g in t.groupby("waterbody"):
        ax.scatter(g["lag1 자기상관"], g["DFA α"], s=10, label=wb)
    ax.set_xlabel("lag-1 자기상관")
    ax.set_ylabel("DFA α")
    ax.legend()
    rep.fig(fig, "memory_scatter.png")
    rep.save()


if __name__ == "__main__":
    main()
