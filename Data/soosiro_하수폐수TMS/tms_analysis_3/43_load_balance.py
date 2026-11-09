# -*- coding: utf-8 -*-
"""
43. 부하 수지(연구 방향 1) — 하천 부하 − 상류 방류 TMS 부하 = 미계측 부하, 유황별 TMS 몫, 처리수 지배 하천, 자료 정합성 점검
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import config as C
from core import Report, io

REQUIRES = ["river_daily", "flow_link", "tms_link", "tms"]
LEVEL = "연계"
VARS = ["TOC", "TN", "TP"]
ZN = [z for _, _, z in C.FLOW_ZONES]


def main():
    rep = Report("43_load_balance", "43. 부하 수지: 방류 TMS 로 설명되지 않는 하천 부하", level=LEVEL,
                 purpose="농도만 비교하면 희석 때문에 기여도를 알 수 없다(방류 TP 가 하천보다 낮은 곳도 있다). "
                         "그래서 '하천 부하(농도×유량) − 상류 방류 TMS 부하'로 미계측 부하(비점·소규모 점오염원·월류·하천 내 생성)를 "
                         "유황별로 나누고, 저유량 때 하천 물의 몇 %가 처리수인지 계산한다. RESEARCH_REVIEW.md 방향 1.")
    tms, sta, f = io.load_tms(), io.load_stations(), io.load_flow()
    if tms is None or f is None:
        return rep.wait("방류 TMS 또는 하천 유량 자료가 없다.", ["tms_analysis_2 tms_clean.pkl", "하천 유량(자료요구서 B-2)"])
    links = sta.dropna(subset=["upstream_tms", "flow_obscd"])
    if links.empty:
        return rep.wait("upstream_tms 와 flow_obscd 가 함께 채워진 측정소가 없다.", ["stations.csv 연결(자료요구서 A-1·A-3, tools/assign_upstream.py)"])
    rep.p("⚠ 측정소-사업장-유량관측소 연결은 현재 추정이다(stations.csv link_note). 결과의 '정합성 점검' 표를 먼저 본다.")
    tms = tms.copy()
    tms["date"] = pd.to_datetime(tms["date"])
    Q = f.pivot_table(index="date", columns="obscd", values="flow_cms", aggfunc="first")
    d = io.load_daily(VARS, quality=False)     # 부하 수지는 유효한 날만으로 계산 가능 → D 등급도 포함하되 '참고'로 표시
    rep.data_info(d[d["station"].isin(links["station"])])
    qf = C.WORK_DIR / "usable_pairs.csv"
    grade = pd.read_csv(qf, encoding="utf-8-sig").set_index(["station", "var"])["등급"].to_dict() if qf.exists() else {}

    zone_rows, qa_rows, year_rows, share_rows = [], [], [], []
    for _, lk in links.iterrows():
        stn, oc = lk["station"], lk["flow_obscd"]
        sites = [s.strip() for s in str(lk["upstream_tms"]).split(";") if s.strip()]
        L = io.tms_upstream_load(tms, sites)
        if L is None or oc not in Q:
            continue
        g = d[d["station"] == stn].set_index("date").asfreq("D")
        q = Q[oc].reindex(g.index)
        q_m3d = q * 86400
        eff = L["Q"].reindex(g.index)
        ratio = eff / q_m3d                                  # 방류수량 / 하천유량
        bad = ratio > 1.0                                    # 방류수가 하천보다 많음 = 유량·연결 불일치
        zone = io.flow_zone(q.where(q > 0))
        low = zone == "저유량"
        qa_rows.append({"측정소": stn, "유량관측소": oc, "사업장": len(sites), "유량·TMS 겹치는 날": int((q.notna() & eff.notna()).sum()),
                        "방류>하천 유량인 날%": float(bad[q.notna() & eff.notna()].mean() * 100),
                        "저유량 방류수 비율(중앙)": float(ratio[low & ~bad].median()),
                        "저유량 희석배수(하천/방류, p10)": float((1 / ratio[low & ~bad]).quantile(0.1))})
        share_rows.append({"station": stn, "저유량 방류수 비율": float(ratio[low & ~bad].median()),
                           "희석배수_p10": float((1 / ratio[low & ~bad]).quantile(0.1)), "sites": ";".join(sites)})
        for v in VARS:
            x = pd.DataFrame({"c": g[v], "q": q, "lt": L[f"{v}_load"].reindex(g.index), "qe": eff, "z": zone}).dropna()
            x = x[(x["q"] > 0) & (x["qe"] / (x["q"] * 86400) <= 1.0)]
            if len(x) < 100:
                continue
            x["lr"] = x["c"] * x["q"] * 86.4                  # kg/일 = mg/L × m³/s × 86.4
            x["un"] = x["lr"] - x["lt"]
            for z in ZN:
                y = x[x["z"] == z]
                if len(y) < 10:
                    continue
                zone_rows.append({"측정소": stn, "항목": v, "품질": grade.get((stn, v), "?"), "유황": z, "일수": len(y), "하천농도": y["c"].median(),
                                  "방류 유량가중농도": y["lt"].sum() / y["qe"].sum() * 1000,
                                  "방류수/하천유량%": (y["qe"] / (y["q"] * 86400)).median() * 100,
                                  "TMS몫%": (y["lt"] / y["lr"]).median() * 100,
                                  "미계측부하(kg/일, 중앙)": y["un"].median(), "TMS몫>100%인 날%": (y["lt"] > y["lr"]).mean() * 100})
            tot_r, tot_t = x["lr"].sum(), x["lt"].sum()
            un_pos = x["un"].clip(lower=0)
            year_rows.append({"측정소": stn, "항목": v, "품질": grade.get((stn, v), "?"), "자료일수": len(x),
                              "하천부하 합(t)": tot_r / 1000, "TMS부하 합(t)": tot_t / 1000,
                              "TMS몫%(기간 합)": tot_t / tot_r * 100, "미계측%(기간 합)": (tot_r - tot_t) / tot_r * 100,
                              **{f"미계측 중 {z}%": un_pos[x["z"] == z].sum() / un_pos.sum() * 100 if un_pos.sum() else np.nan for z in ZN}})
    qa, zt, yt = pd.DataFrame(qa_rows), pd.DataFrame(zone_rows), pd.DataFrame(year_rows)
    if zt.empty:
        return rep.wait("연결된 측정소에서 유량·TMS·수질이 함께 있는 날이 부족하다.")
    pd.DataFrame(share_rows).to_csv(C.WORK_DIR / "effluent_share.csv", index=False, encoding="utf-8-sig")

    rep.h("1. 정합성 점검(먼저 볼 것)")
    rep.table(qa.round(3))
    rep.p("'방류>하천 유량인 날'이 많으면 유량관측소 위치(측정소보다 상류?), 저유량 수위-유량 관계식 오차, 사업장 연결(하류 방류 사업장 포함)을 점검한다. "
          "이런 날은 아래 계산에서 뺐다.")
    unreliable = set(qa.loc[qa["방류>하천 유량인 날%"] >= 10, "측정소"])
    for _, r in qa.iterrows():
        if r["측정소"] in unreliable:
            rep.finding(f"⚠ {r['측정소']}: 방류수량이 하천 유량보다 큰 날 {r['방류>하천 유량인 날%']:.0f}% — 유량관측소·사업장 연결 재확인 전까지 해석 보류")
        elif r["저유량 방류수 비율(중앙)"] >= C.EFFLUENT_DOMINATED:
            rep.finding(f"{r['측정소']}: 저유량 때 하천 물의 {r['저유량 방류수 비율(중앙)']:.0%}가 처리수(희석배수 p10 {r['저유량 희석배수(하천/방류, p10)']:.1f}배) "
                        "— '처리수 지배 하천', 방류수질이 곧 하천수질")

    rep.h("2. 유황별 부하 구성")
    rep.table(zt.round(3))
    rep.csv(zt, "balance_by_zone.csv")
    rep.p("방류 유량가중농도와 하천농도를 나란히 둔 것은 '농도 비교의 함정'을 보여주기 위함이다. TMS몫% = 상류 방류 부하 ÷ 하천 부하.")
    for (stn, v), g in zt.groupby(["측정소", "항목"]):
        if stn in unreliable:
            continue
        tag = " (자료 커버리지 낮음·참고)" if g["품질"].iloc[0] == "D" else ""
        g = g.set_index("유황")
        if {"저유량", "고유량"} <= set(g.index):
            lo, hi = g.loc["저유량", "TMS몫%"], g.loc["고유량", "TMS몫%"]
            if lo <= 150:
                rep.finding(f"{stn} {v}: 하천 부하 중 방류 TMS 몫 저유량 {lo:.0f}% → 고유량 {hi:.0f}% "
                            + ("— 대부분 TMS 밖 부하(비점·소규모 오염원)" if lo < 30 else "— 평상시 점오염 비중 큼") + tag)

    rep.h("3. 기간 합계와 미계측 부하가 생기는 유황")
    rep.table(yt.round(1))
    rep.csv(yt, "balance_totals.csv")
    for _, r in yt.iterrows():
        un, hi_share = r["미계측%(기간 합)"], r.get("미계측 중 고유량%", np.nan)
        if r["측정소"] in unreliable or pd.isna(un) or un <= 0:
            continue
        tag = " (자료 커버리지 낮음·참고)" if r["품질"] == "D" else ""
        rep.finding(f"{r['측정소']} {r['항목']}: 기간 하천 부하의 {un:.0f}%가 미계측, 그중 {hi_share:.0f}%가 유량 상위 10% 날에 발생{tag}")
    rep.p("미계측 부하 = 비점오염 + TMS 미부착 점오염원(소규모 처리시설·개인하수·축산) + 합류식 월류·처리장 우회 + 하천 내 생성(조류 → TOC) "
          "− 하천 내 감소(침강·탈질). 비점만 따로 떼려면 44번(강우 초과 부하)과 전국오염원조사(자료요구서 D-4)를 함께 쓴다.")

    fig, axes = plt.subplots(1, len(VARS), figsize=(5 * len(VARS), 4), squeeze=False)
    for ax, v in zip(axes[0], VARS):
        z = zt[zt["항목"] == v].pivot_table(index="측정소", columns="유황", values="TMS몫%").reindex(columns=ZN)
        if z.empty:
            ax.set_visible(False)
            continue
        z.clip(upper=150).plot.bar(ax=ax)
        ax.axhline(100, color="r", lw=0.8, ls="--")
        ax.set_title(f"{v}: 하천 부하 중 TMS 몫(%)")
        ax.set_xlabel("")
    fig.tight_layout()
    rep.fig(fig, "tms_share_by_zone.png", "유황별 하천 부하 중 상류 방류 TMS 몫(150% 에서 자름, 빨간 선 = 100%)")
    rep.save()


if __name__ == "__main__":
    main()
