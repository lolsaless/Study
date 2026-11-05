# -*- coding: utf-8 -*-
"""
40. 기상 연계 — 강우 사건 반응(사건일/건기 비), 분포시차 회귀(비 온 뒤 며칠째 최대 반응), 기온–수온 민감도, 하천 정의 사건일 검증
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

REQUIRES = ["river_daily", "weather_daily", "weather_link"]
LEVEL = "연계"
VARS = ["Turb", "TP", "TOC", "TN", "EC", "Chl_a", "DO"]
MAXLAG = 5


def main():
    rep = Report("40_weather_link", "40. 기상 연계: 비와 기온에 대한 하천 반응", level=LEVEL,
                 purpose="측정소와 연결된 기상 지점(stations.csv 의 weather_stn)의 강수·기온으로 ① 강우 사건 때 항목별 변화 배율, "
                         "② 비 온 뒤 며칠째 반응이 최대인지(분포시차), ③ 기온이 1℃ 오를 때 수온이 얼마나 오르는지(열 민감도)를 계산한다.")
    w = io.load_weather()
    sta = io.load_stations()
    if w is None or sta["weather_stn"].isna().all():
        return rep.wait("기상 일자료 또는 측정소-기상지점 연결이 없다.", ["기상청 ASOS 일자료(자료요구서 B-1)", "stations.csv weather_stn"])
    w = w[w["stn"].isin(sta["weather_stn"].dropna().unique())]
    links = sta.dropna(subset=["weather_stn"])
    links = links[links["weather_stn"].isin(w["stn"].unique())]
    if links.empty:
        return rep.wait("연결된 기상 지점의 자료가 없다(지점 번호 확인).", ["collectors/collect_kma_asos_daily.py 로 해당 지점 수집"])
    d = io.load_daily(VARS + ["WT"])
    d = d[d["station"].isin(links["station"])]
    rep.data_info(d)
    rep.kv({"기상 연결 측정소": d["station"].nunique(), "사용 기상 지점": links["weather_stn"].nunique(),
            "자료가 없어 빠진 측정소": int(sta["station"].nunique() - d["station"].nunique())})
    W = w.pivot_table(index="date", columns="stn", values=["rain_mm", "ta_mean"], aggfunc="first")
    ev_rows, lag_rows, th_rows = [], [], []
    for stn_name, g in d.groupby("station"):
        ws = links.set_index("station").loc[stn_name, "weather_stn"]
        g = g.set_index("date").sort_index().asfreq("D")
        rain = W["rain_mm"][ws].reindex(g.index) if ws in W["rain_mm"] else None
        if rain is None or rain.notna().sum() < 300:
            continue
        r2d = rain.fillna(0) + rain.shift(1).fillna(0)
        event = r2d >= C.EVENT_MM
        evd = event | event.shift(1, fill_value=False)
        dry = rain.fillna(0).rolling(C.DRY_PRIOR_DAYS + 1).max() < C.WET_DAY_MM
        for v in VARS:
            s = g[v]
            if s.notna().sum() < 200:
                continue
            base = s.where(dry).rolling(31, center=True, min_periods=8).median()
            ratio = (s / base) if v != "DO" else (s - base)
            a, b = ratio[evd].dropna(), ratio[dry].dropna()
            if len(a) >= 8 and len(b) >= 30:
                ev_rows.append({"basin": g["basin"].dropna().iloc[0], "station": stn_name, "var": v, "사건일": len(a),
                                "사건/건기(중앙)": a.median(), "건기 기준 중앙": b.median(),
                                "p": stats.mannwhitneyu(a, b).pvalue})
            y = st.deseason(s, v).dropna()
            X = pd.concat({f"L{k}": np.log1p(rain.fillna(0)).shift(k) for k in range(MAXLAG + 1)}, axis=1).reindex(y.index).dropna()
            yy = y.reindex(X.index)
            if len(yy) > 200:
                A = np.column_stack([np.ones(len(X)), X.values])
                beta = np.linalg.lstsq(A, yy.values, rcond=None)[0][1:]
                lag_rows.append({"station": stn_name, "var": v, **{f"L{k}": beta[k] for k in range(MAXLAG + 1)},
                                 "최대반응 시차(일)": int(np.argmax(np.abs(beta)))})
        if ws in W["ta_mean"] and g["WT"].notna().sum() > 300:
            ta7 = W["ta_mean"][ws].reindex(g.index).rolling(7, min_periods=5).mean()
            x = pd.concat([ta7, g["WT"]], axis=1).dropna()
            if len(x) > 200:
                sl = stats.linregress(x.iloc[:, 0], x.iloc[:, 1])
                warm = x[x.iloc[:, 0] > 15]
                sw = stats.linregress(warm.iloc[:, 0], warm.iloc[:, 1]).slope if len(warm) > 60 else np.nan
                th_rows.append({"station": stn_name, "waterbody": g["waterbody"].dropna().iloc[0], "기온7일→수온 기울기": sl.slope,
                                "R²": sl.rvalue ** 2, "기온>15℃ 구간 기울기": sw, "수온-기온(여름 평균)": (x.iloc[:, 1] - x.iloc[:, 0])[x.index.month.isin([7, 8])].mean()})
    ev, lg, th = pd.DataFrame(ev_rows), pd.DataFrame(lag_rows), pd.DataFrame(th_rows)
    if ev.empty:
        return rep.wait("연결된 측정소에서 사건 반응을 계산할 자료가 부족하다.")
    ev["q"] = st.fdr(ev["p"])
    rep.csv(ev, "rain_event_response.csv")
    rep.h(f"1. 강우 사건(2일 누적 ≥ {C.EVENT_MM:g} mm, 당일·다음날) vs 건기")
    s = ev.groupby("var").agg(측정소=("station", "size"), 배율중앙=("사건/건기(중앙)", "median"),
                              p10=("사건/건기(중앙)", lambda x: x.quantile(0.1)), p90=("사건/건기(중앙)", lambda x: x.quantile(0.9)),
                              유의증가=("q", lambda x: 0)).reindex(VARS).dropna(how="all")
    s["유의증가"] = [int(((ev["var"] == v) & (ev["q"] < 0.05) & (ev["사건/건기(중앙)"] > (0 if v == "DO" else 1))).sum()) for v in s.index]
    rep.table(s.round(3), index=True)
    rep.p("DO 는 비율이 아니라 차이(mg/L). 배율은 31일 건기 기준선 대비.")
    for v in ["Turb", "TP", "TOC", "EC"]:
        if v in s.index:
            rep.finding(f"강우 사건 시 {v} 건기 대비 ×{s.loc[v, '배율중앙']:.2f} (측정소 {int(s.loc[v, '측정소'])}곳 중앙, p10~p90 {s.loc[v, 'p10']:.2f}~{s.loc[v, 'p90']:.2f})")
    if len(lg):
        rep.h("2. 분포시차 회귀: 비 온 뒤 며칠째 반응이 가장 큰가")
        rep.table(lg.groupby("var")[[f"L{k}" for k in range(MAXLAG + 1)] + ["최대반응 시차(일)"]].median().round(3), index=True)
        rep.csv(lg, "rain_lag_response.csv")
        mx = lg.groupby("var")["최대반응 시차(일)"].median()
        rep.finding("비 온 뒤 최대 반응 시차(측정소 중앙): " + ", ".join(f"{k} {int(v)}일" for k, v in mx.items()))
    if len(th):
        rep.h("3. 기온 → 수온 열 민감도")
        rep.table(th.sort_values("기온7일→수온 기울기").round(3))
        rep.csv(th, "thermal_sensitivity.csv")
        lo = th.sort_values("기온7일→수온 기울기").head(3)
        rep.finding(f"수온의 기온 민감도 중앙 {th['기온7일→수온 기울기'].median():.2f}℃/℃ — 가장 둔감: "
                    + ", ".join(f"{a}({b:.2f})" for a, b in zip(lo['station'], lo['기온7일→수온 기울기']))
                    + " → 댐 저층 방류·지하수 유입 영향 의심, 기후변화 수온 상승에 덜 민감")
    rep.h("4. 하천 자료로 정의한 사건일(30번)의 검증")
    sev = station_events(d)
    chk = []
    for stn_name, g in sev.groupby("station"):
        ws = links.set_index("station").loc[stn_name, "weather_stn"]
        if ws not in W["rain_mm"]:
            continue
        r = W["rain_mm"][ws].reindex(pd.to_datetime(g["date"])).fillna(0).values
        r2 = r + np.r_[0, r[:-1]]
        e = g["event"].values
        if e.sum() > 5:
            chk.append({"station": stn_name, "하천사건일": int(e.sum()), "그중 2일강수≥10mm 비율": float((r2[e] >= 10).mean())})
    if chk:
        ck = pd.DataFrame(chk)
        rep.table(ck.describe().round(2), index=True)
        rep.finding(f"탁도·EC 로 정의한 하천 사건일의 {ck['그중 2일강수≥10mm 비율'].median():.0%}(측정소 중앙)가 실제 강우(2일 ≥10 mm)와 일치 — 기상자료 없는 수계에서 대용 가능")
    if len(lg):
        fig, ax = plt.subplots(figsize=(7, 4))
        for v, g in lg.groupby("var"):
            ax.plot(range(MAXLAG + 1), g[[f"L{k}" for k in range(MAXLAG + 1)]].median(), marker="o", label=v)
        ax.axhline(0, color="gray")
        ax.set_xlabel("강수 후 경과일")
        ax.set_ylabel("log1p(강수) 계수(계절 제거 로그편차)")
        ax.legend()
        rep.fig(fig, "rain_lag_profile.png")
    rep.save()


if __name__ == "__main__":
    main()
