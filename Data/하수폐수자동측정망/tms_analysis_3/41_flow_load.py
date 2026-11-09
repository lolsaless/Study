# -*- coding: utf-8 -*-
"""
41. 유량 연계 — 농도–유량(C–Q) 관계로 오염원 유형 진단, 부하량, '고유량 10% 날'의 부하 비중, 부하지속곡선(LDC)으로 기준 초과가 생기는 유황
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats

import config as C
from core import Report, io

REQUIRES = ["river_daily", "flow_daily", "flow_link"]
LEVEL = "연계"
VARS = ["TOC", "TN", "TP", "Turb", "EC"]
ZONES = [(0, 10, "홍수기"), (10, 40, "풍수"), (40, 60, "평수"), (60, 90, "저수"), (90, 100, "갈수")]


def main():
    rep = Report("41_flow_load", "41. 유량 연계: C–Q 관계, 부하량, 부하지속곡선", level=LEVEL,
                 purpose="농도가 유량에 따라 어떻게 바뀌는지(희석형 = 점오염 우세, 유출형 = 비점오염 우세)를 진단하고, "
                         "연간 부하의 몇 %가 '가장 물이 많은 10% 날'에 나가는지, 기준 초과가 어떤 유황에서 생기는지 계산한다.")
    f = io.load_flow()
    sta = io.load_stations()
    if f is None or sta["flow_obscd"].isna().all():
        return rep.wait("유량 자료 또는 측정소-유량관측소 연결이 없다.", ["하천 유량 일자료(자료요구서 B-2)", "stations.csv flow_obscd"])
    links = sta.dropna(subset=["flow_obscd"])
    Q = f.pivot_table(index="date", columns="obscd", values="flow_cms", aggfunc="first")
    d = io.load_daily(VARS)
    d = d[d["station"].isin(links["station"])]
    rep.data_info(d)
    rows, zone_rows, loads, ldc = [], [], [], {}
    for stn, g in d.groupby("station"):
        oc = links.set_index("station").loc[stn, "flow_obscd"]
        if oc not in Q or Q[oc].notna().sum() < 200:
            continue
        g = g.set_index("date").sort_index()
        q = Q[oc].reindex(g.index)
        qall = Q[oc].dropna()
        qall = qall[qall > 0]
        pexc = q.map(lambda v: (qall >= v).mean() * 100 if pd.notna(v) else np.nan)
        wb = g["waterbody"].dropna().iloc[0]
        stdtab = C.LAKE_STD if wb == "호소" else C.RIVER_STD
        for v in VARS:
            x = pd.concat([g[v], q], axis=1, keys=["c", "q"]).dropna()
            x = x[(x["c"] > 0) & (x["q"] > 0)]
            if len(x) < 150:
                continue
            sl = stats.linregress(np.log(x["q"]), np.log(x["c"]))
            cvr = (x["c"].std() / x["c"].mean()) / (x["q"].std() / x["q"].mean())
            typ = "유출형(비점↑)" if sl.slope > 0.1 else ("희석형(점오염)" if sl.slope < -0.1 else "항상성")
            r = {"station": stn, "flow_obscd": oc, "var": v, "n": len(x), "C–Q 기울기 b": sl.slope, "R²": sl.rvalue ** 2,
                 "CVc/CVq": cvr, "유형": typ}
            if v in ["TOC", "TN", "TP"]:
                L = x["c"] * x["q"] * 86.4                      # kg/일 = mg/L × m³/s × 86.4
                top = x["q"] >= x["q"].quantile(0.9)
                r["고유량10%일 부하비중%"] = L[top].sum() / L.sum() * 100
                r["일평균부하(kg/일)"] = L.mean()
                loads.append(L.rename(f"{stn}|{v}"))
                if v in stdtab:
                    lim = stdtab[v][C.GRADES.index(C.TARGET_GRADE)]
                    pe = pexc.reindex(x.index)
                    for lo, hi, zn in ZONES:
                        m = (pe >= lo) & (pe < hi)
                        if m.sum() >= 10:
                            zone_rows.append({"station": stn, "var": v, "유황": zn, "일수": int(m.sum()),
                                              "목표초과%": float((x.loc[m, "c"] > lim).mean() * 100)})
                    ldc[(stn, v)] = (pe, x["c"], x["q"], lim)
            rows.append(r)
    t = pd.DataFrame(rows)
    if t.empty:
        return rep.wait("연결된 관측소에 유량 자료가 부족하다.")
    rep.csv(t, "cq_by_station.csv")
    rep.h("1. C–Q 관계(log C = a + b·log Q)")
    rep.table(t[["station", "var", "n", "C–Q 기울기 b", "R²", "CVc/CVq", "유형"]].round(3))
    rep.p("b > 0.1 유출형(비 올 때 농도↑ = 비점·토사), b < −0.1 희석형(평상시 점오염이 농도를 결정), 그 사이 항상성. "
          "CVc/CVq < 0.5 이면 농도 변동이 유량 변동보다 훨씬 작다(화학적 항상성).")
    for v in ["TP", "TOC", "TN"]:
        x = t[t["var"] == v]
        if len(x):
            vc = x["유형"].value_counts()
            rep.finding(f"{v} C–Q 유형: " + ", ".join(f"{k} {n}곳" for k, n in vc.items()) + f" (b 중앙 {x['C–Q 기울기 b'].median():+.2f})")
    if "고유량10%일 부하비중%" in t:
        rep.h("2. 고유량 10% 날이 실어 나르는 부하 비중")
        lw = t.dropna(subset=["고유량10%일 부하비중%"]).pivot_table(index="station", columns="var", values="고유량10%일 부하비중%")
        rep.table(lw.round(1), index=True)
        for v in lw.columns:
            rep.finding(f"{v} 연간 부하의 {lw[v].median():.0f}%(측정소 중앙)가 유량 상위 10% 날에 이동 — 강우기 관리가 부하 저감의 핵심" if lw[v].median() > 30
                        else f"{v} 유량 상위 10% 날의 부하 비중 {lw[v].median():.0f}% — 평상시 부하 관리도 중요")
    if zone_rows:
        rep.h(f"3. 부하지속곡선: 유황별 목표({C.TARGET_GRADE}등급) 초과 비율")
        z = pd.DataFrame(zone_rows).pivot_table(index=["station", "var"], columns="유황", values="목표초과%")
        z = z.reindex(columns=[zn for _, _, zn in ZONES])
        rep.table(z.round(0), index=True)
        rep.csv(z.reset_index(), "ldc_zone_exceed.csv")
        rep.p("홍수기·풍수에서 초과가 몰리면 비점오염, 저수·갈수에서 몰리면 점오염(하수·폐수) 관리가 우선이다.")
        for (stn, v), r in z.iterrows():
            if r.notna().sum() >= 3 and r.max() >= 20:
                if r.min() >= 80:
                    rep.finding(f"{stn} {v}: 모든 유황에서 목표 초과(최소 {r.min():.0f}%) → 유량과 무관한 상시 부하 = 점오염 우선")
                else:
                    rep.finding(f"{stn} {v}: 목표 초과가 '{r.idxmax()}' 유황에서 최대({r.max():.0f}%) → " +
                                ("비점오염 우선" if r.idxmax() in ("홍수기", "풍수") else "점오염 우선"))
        keys = list(ldc)[:6]
        if keys:
            fig, axes = plt.subplots(2, 3, figsize=(14, 7))
            for ax, k in zip(axes.flat, keys):
                pe, c, q, lim = ldc[k]
                ax.scatter(pe.reindex(c.index), c * q * 86.4, s=4, alpha=0.5)
                qs = np.sort(q.values)[::-1]
                ax.plot(np.linspace(0, 100, len(qs)), qs * lim * 86.4, color="r", label="목표 부하")
                ax.set_yscale("log")
                ax.set_title(f"{k[0]} {k[1]}")
                ax.set_xlabel("유량 초과확률(%)")
            axes.flat[0].legend()
            fig.tight_layout()
            rep.fig(fig, "load_duration_curves.png", "부하지속곡선(점 = 관측 부하, 빨강 = 목표 농도×유량)")
    rep.save()


if __name__ == "__main__":
    main()
