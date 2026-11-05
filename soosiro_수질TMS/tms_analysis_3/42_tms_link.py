# -*- coding: utf-8 -*-
"""
42. 방류수 TMS × 하천 연계 — 상류 사업장 부하와 하천 농도의 요일 지문 일치, 시차 교차상관, (유량이 있으면) 건기 하천 부하 중 TMS 점오염 기여율
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

REQUIRES = ["river_daily", "tms_link", "tms"]
LEVEL = "연계"
PAIRS = [("TOC", "TOC_load"), ("TN", "TN_load"), ("TP", "TP_load"), ("EC", "TOC_load")]
DOW = ["월", "화", "수", "목", "금", "토", "일"]


def main():
    rep = Report("42_tms_link", "42. 방류수 TMS × 하천 연계(점오염 추적)", level=LEVEL,
                 purpose="stations.csv 의 upstream_tms(상류 사업장)와 tms_analysis_2 의 방류 TMS 일자료를 붙여, "
                         "하천 수질 변동에 처리장 방류가 남긴 흔적(요일 지문·시차 상관)과 건기 하천 부하 중 TMS 몫을 계산한다.")
    tms = io.load_tms()
    sta = io.load_stations()
    if tms is None:
        return rep.wait(f"TMS 정제자료가 없다: {C.TMS_CLEAN_PKL}", ["tms_analysis_2 에서 01_preprocess.py 실행"])
    links = sta.dropna(subset=["upstream_tms"])
    if links.empty:
        return rep.wait("stations.csv 의 upstream_tms 가 비어 있다.", ["측정소-상류 사업장 연결(자료요구서 A-3)"])
    rep.p("⚠ 측정소-사업장 연결은 행정구역 기반 가설이다(link_note). 유역 경계·측정소 좌표로 확인 후 고칠 것.")
    tms = tms.copy()
    tms["date"] = pd.to_datetime(tms["date"])
    d = io.load_daily(["TOC", "TN", "TP", "EC", "Turb"])
    d = d[d["station"].isin(links["station"])]
    rep.data_info(d)
    ev = station_events(d)
    flow = io.load_flow()
    Q = flow.pivot_table(index="date", columns="obscd", values="flow_cms", aggfunc="first") if flow is not None else None
    hol = set(io.holidays())
    wk_rows, cc_rows, share_rows, profs = [], [], [], {}
    for _, lk in links.iterrows():
        stn = lk["station"]
        sites = [s.strip() for s in str(lk["upstream_tms"]).split(";") if s.strip()]
        t = tms[tms["site"].isin(sites)]
        if t.empty:
            continue
        n_site = t.groupby("date")["site"].nunique()
        full = n_site >= 0.8 * t["site"].nunique()
        L = t.groupby("date")[["TOC_load", "TN_load", "TP_load"]].sum().where(full)
        L = L.asfreq("D")
        g = d[d["station"] == stn].set_index("date").asfreq("D")
        e = ev[ev["station"] == stn].set_index("date")["dry"].reindex(g.index).fillna(False).astype(bool)
        for rv, tv in PAIRS:
            if g[rv].notna().sum() < 200:
                continue
            ra = st.deseason(g[rv], rv, 29)
            ta = st.deseason(L[tv].reindex(g.index), "TP", 29)        # 부하는 로그 편차
            ok = e & ~g.index.isin(hol)
            rw = ra[ok].groupby(ra[ok].index.dayofweek).mean()
            tw = ta[ok].groupby(ta[ok].index.dayofweek).mean()
            if len(rw) == 7 and len(tw) == 7:
                best = max(range(4), key=lambda k: np.corrcoef(rw.values, np.roll(tw.values, k))[0, 1])
                r_best = np.corrcoef(rw.values, np.roll(tw.values, best))[0, 1]
                H, p = stats.kruskal(*[ra[ok][ra[ok].index.dayofweek == k].dropna() for k in range(7)])
                amp = (np.exp(rw.max() - rw.min()) - 1) * 100 if rv in C.LOG_VARS else rw.max() - rw.min()
                tamp = (np.exp(tw.max() - tw.min()) - 1) * 100
                wk_rows.append({"station": stn, "하천항목": rv, "TMS부하": tv, "하천 요일진폭%": amp, "TMS 요일진폭%": tamp,
                                "요일패턴 상관 r": r_best, "지연(일)": best, "하천 요일차 p": p, "사업장": len(sites)})
                profs[(stn, rv)] = ((np.exp(rw - rw.mean()) - 1) * 100, (np.exp(tw - tw.mean()) - 1) * 100)
            lag, r, _ = st.ccf_best_lag(st.prewhiten(ta), st.prewhiten(ra), max_lag=3)
            cc_rows.append({"station": stn, "하천항목": rv, "TMS부하": tv, "최대상관 지연(일)": lag, "r": r})
            if Q is not None and pd.notna(lk.get("flow_obscd")) and lk["flow_obscd"] in Q and rv in ("TOC", "TN", "TP"):
                q = Q[lk["flow_obscd"]].reindex(g.index)
                river_load = g[rv] * q * 86.4
                sh = (L[tv].reindex(g.index) / river_load).replace([np.inf, -np.inf], np.nan)
                share_rows.append({"station": stn, "항목": rv, "건기 TMS 기여율 중앙": sh[e].median(),
                                   "강우기 TMS 기여율 중앙": sh[~e].median(), "건기일": int((e & sh.notna()).sum())})
    wk, cc, sh = pd.DataFrame(wk_rows), pd.DataFrame(cc_rows), pd.DataFrame(share_rows)
    if wk.empty and cc.empty:
        return rep.wait("연결된 사업장 이름이 TMS 자료와 맞지 않거나 기간이 겹치지 않는다(upstream_tms 철자 확인).")
    wk["q"] = st.fdr(wk["하천 요일차 p"])
    rep.h("1. 요일 지문 일치(건기·공휴일 제외)")
    rep.table(wk.round(3))
    rep.csv(wk, "weekday_match.csv")
    strong = wk[(wk["요일패턴 상관 r"] > 0.8) & (wk["q"] < 0.05)]
    for r in strong.itertuples():
        rep.finding(f"{r.station} {r.하천항목}: 상류 TMS {r.TMS부하} 요일 패턴과 r={r._6:.2f}(지연 {r._7}일), 하천 요일 진폭 {r._4:.0f}% — 처리장 방류가 하천 변동을 만든다")
    rep.h("2. 계절 제거 편차의 시차 교차상관(사전백색화, TMS가 앞설 때 양의 지연)")
    rep.table(cc.round(3))
    if len(sh):
        rep.h("3. 하천 부하 중 상류 TMS 방류 부하 비율(유량 연결 측정소)")
        rep.table(sh.round(3))
        rep.csv(sh, "tms_share.csv")
        rep.p("기여율 = 상류 TMS 방류 부하 합 ÷ (하천 농도 × 하천 유량). 1을 넘으면 연결·유량·감쇠(하천 내 분해·침강) 가정을 점검한다. "
              "건기 > 강우기 이면 강우 때 TMS 밖(비점·월류)의 부하가 커진다는 뜻(v2 RESEARCH_REVIEW 4.3).")
        for r in sh.itertuples():
            warn = " (100% 초과 → 사업장 연결·유량 관측소 위치 점검 필요)" if r._3 > 1 else ""
            rep.finding(f"{r.station} {r.항목}: 상류 TMS 방류가 하천 부하에서 차지하는 비율 건기 {r._3:.0%} → 강우기 {r._4:.0%}{warn}")
    if profs:
        keys = list(profs)[:6]
        fig, axes = plt.subplots(1, len(keys), figsize=(4 * len(keys), 3.5), squeeze=False)
        for ax, k in zip(axes[0], keys):
            rw, tw = profs[k]
            ax.plot(DOW, rw.values, marker="o", label="하천")
            ax.plot(DOW, tw.values, marker="s", label="상류 TMS 부하")
            ax.set_title(f"{k[0]} {k[1]}")
            ax.axhline(0, color="gray", lw=0.5)
        axes[0][0].legend()
        rep.fig(fig, "weekday_match.png", "요일 편차(%) — 하천 vs 상류 TMS")
    rep.save()


if __name__ == "__main__":
    main()
