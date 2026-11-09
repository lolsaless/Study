# -*- coding: utf-8 -*-
"""
30. 이상 사건 탐지·유형 분류 — 강건 z(계절 제거) + 다변량 Isolation Forest, 사건 유형(유출·조류·저산소·오염 의심·센서 의심), 광역 사건일
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import config as C
from core import Report, io, st
from core.events import station_events, regional_events

REQUIRES = ["river_daily"]
LEVEL = "심화"
VARS = ["WT", "pH", "EC", "DO", "Turb", "TOC", "TN", "TP", "Chl_a"]
Z = C.ANOMALY_Z


def classify(r):
    z = r
    up = lambda v: z.get(v, 0) > Z          # noqa: E731
    dn = lambda v: z.get(v, 0) < -Z         # noqa: E731
    n_big = sum(abs(z.get(v, 0)) > Z for v in VARS)
    if up("Turb") or (dn("EC") and (up("TP") or up("TOC"))):
        return "강우 유출(탁도↑·희석)"
    if up("Chl_a") and (up("DO") or up("pH")):
        return "조류 번성(Chl-a↑·광합성)"
    if r.get("DO_min_raw", 99) < C.HYPOXIA_DO and dn("DO"):
        return "저산소"
    n_conc = sum(up(v) for v in ["TOC", "TN", "TP", "EC"])
    if n_conc >= 2 and not up("Turb") and not dn("EC"):      # 희석(EC↓)·탁도 상승 없이 2개 이상 농도 동시 상승
        return "오염 유입 의심(탁도 없이 농도↑)"
    if n_conc == 1 and n_big == 1:
        return "단일 항목 급등(센서·국지 오염 확인)"
    if dn("EC") and n_conc:
        return "희석 동반 농도↑(강우 초기 세척 가능)"
    if n_big == 1:
        return "단일 항목 이상(센서 의심)"
    return "기타"


def main():
    rep = Report("30_anomaly_events", "30. 이상 사건 탐지와 유형 분류", level=LEVEL,
                 purpose="계절을 뺀 편차가 평소보다 크게 벗어난 날을 찾고, 함께 움직인 항목으로 사건의 성격(비·조류·저산소·오염·센서)을 분류한다. "
                         "'탁도 상승 없이 TOC·TN·EC 가 함께 오른 날'은 강우가 아닌 배출 사건 후보다.")
    d = io.load_daily(VARS, minmax=True)
    rep.data_info(d)
    zs = []
    for b, stn, v, s in io.iter_series(d, VARS, min_days=200):
        a = st.deseason(s, v)
        zs.append(pd.DataFrame({"basin": b, "station": stn, "date": a.index, "var": v, "z": st.robust_z(a).values}))
    Zl = pd.concat(zs)
    W = Zl.pivot_table(index=["basin", "station", "date"], columns="var", values="z").reset_index()
    W = W.merge(d[["station", "date", "DO_min"]].rename(columns={"DO_min": "DO_min_raw"}), on=["station", "date"], how="left")
    big = W[VARS].abs().gt(Z).any(axis=1) if set(VARS) <= set(W.columns) else W[[c for c in VARS if c in W]].abs().gt(Z).any(axis=1)
    ev = W[big].copy()          # 만성 저산소(매일 낮은 곳)는 사건이 아니므로, 편차가 큰 날 중에서만 저산소를 분류
    ev["유형"] = ev.apply(lambda r: classify(r.to_dict()), axis=1)
    ev["관련항목"] = ev[[c for c in VARS if c in ev]].apply(lambda r: ", ".join(f"{k}{'↑' if x > 0 else '↓'}" for k, x in r.items() if abs(x) > Z), axis=1)
    rep.csv(ev[["basin", "station", "date", "유형", "관련항목", "DO_min_raw"] + [c for c in VARS if c in ev]], "events.csv")

    rep.h("1. 사건 유형 집계")
    tab = ev.pivot_table(index="유형", columns="basin", values="date", aggfunc="count", fill_value=0)
    tab["합계"] = tab.sum(axis=1)
    rep.table(tab.sort_values("합계", ascending=False), index=True)
    poll = ev[ev["유형"].str.startswith("오염")]
    rep.finding(f"사건일 {len(ev):,}건 — 유형 최다: {tab['합계'].idxmax()} {int(tab['합계'].max()):,}건")
    if len(poll):
        top = poll.groupby("station").size().sort_values(ascending=False).head(5)
        rep.finding("탁도 없이 농도가 함께 오른 '오염 유입 의심' 사건이 많은 측정소: " + ", ".join(f"{k} {v}건" for k, v in top.items()))
        rep.table(poll.sort_values("date").tail(25)[["basin", "station", "date", "관련항목"]], "오염 유입 의심 사건(최근 25건)")

    rep.h("2. 다변량 이상(Isolation Forest, 측정소별 상위 1%)")
    try:
        from sklearn.ensemble import IsolationForest
        iso_rows = []
        for stn, g in W.groupby("station"):
            cols = [c for c in VARS if c in g and g[c].notna().mean() > 0.6]
            x = g.dropna(subset=cols)
            if len(x) < 200 or len(cols) < 4:
                continue
            m = IsolationForest(contamination=0.01, random_state=C.RANDOM_STATE).fit(x[cols].clip(-15, 15))
            sc = -m.score_samples(x[cols].clip(-15, 15))
            flag = m.predict(x[cols].clip(-15, 15)) == -1
            for (_, r), s_ in zip(x[flag].iterrows(), sc[flag]):
                single = (r[cols].abs() > Z).sum() == 0
                iso_rows.append({"station": stn, "date": r["date"], "점수": s_, "단변량으로는 안 잡힘": bool(single),
                                 "가장 벗어난 항목": ", ".join(r[cols].abs().sort_values(ascending=False).index[:3])})
        iso = pd.DataFrame(iso_rows)
        rep.csv(iso, "isolation_forest.csv")
        hidden = iso[iso["단변량으로는 안 잡힘"]]
        rep.p(f"다변량 이상일 {len(iso)}건 중 {len(hidden)}건은 어떤 항목도 단독으로는 기준(|z|>{Z})을 넘지 않았다 — "
              "'항목 조합이 평소와 다른 날'(예: 수온 대비 DO 가 낮음)이다.")
        rep.table(hidden.sort_values("점수", ascending=False).head(15))
        rep.finding(f"다변량 Isolation Forest 이상일 {len(iso)}건 중 {len(hidden)}건({len(hidden) / max(len(iso), 1):.0%})은 단변량 기준으로 놓치는 '조합 이상'")
    except ImportError:
        rep.p("scikit-learn 이 없어 다변량 탐지는 생략했다(pip install scikit-learn).")

    rep.h("3. 광역 사건일(같은 수계 측정소 25% 이상이 강우 유출 신호)")
    sev = station_events(d)
    reg = regional_events(sev)
    rr = reg[reg["regional"]]
    rep.table(rr.groupby("basin").agg(광역사건일=("date", "size"), 여름비율=("date", lambda s: s.dt.month.between(6, 9).mean())).reset_index())
    rr.to_csv(C.WORK_DIR / "regional_event_days.csv", index=False, encoding="utf-8-sig")
    rep.p("이 광역 사건일은 기상자료가 없을 때 '강우일' 대용으로 쓸 수 있다(work/regional_event_days.csv).")
    fig, ax = plt.subplots(figsize=(12, 3))
    for i, b in enumerate(C.BASINS):
        x = rr[rr["basin"] == b]["date"]
        ax.scatter(x, [i] * len(x), s=8)
    ax.set_yticks(range(4), C.BASINS)
    rep.fig(fig, "regional_events.png", "수계별 광역 강우 유출 사건일")
    rep.save()


if __name__ == "__main__":
    main()
