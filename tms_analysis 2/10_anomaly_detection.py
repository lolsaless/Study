# -*- coding: utf-8 -*-
"""
10. 이상치(이상 사건) 탐지
- 단변량: 이동 중앙값 편차의 강건 z-점수(|z|>ANOMALY_Z)
- 다변량: Isolation Forest(로그 TOC·SS·TN·TP·Q, pH) — 항목 조합이 평소와 다른 날
- 사건 유형 분류: 유량만 급증(수리 충격) / SS+TP 동반 급증(슬러지 유출 의심) / TN 단독 상승(질산화 저하 의심) 등
- 여러 처리장이 같은 날 이상 → 광역 사건일(강우·한파 후보) 목록
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import config as C
from common import Report, load_clean, valid_sids, daily, anomaly, need

VARS = ["Q", "TOC", "SS", "TN", "TP"]
RESOLUTION = {"TOC": 0.1, "SS": 0.1, "TN": 0.001, "TP": 0.001, "Q": None}   # [v2] 기록 해상도


def classify(row):
    hi = {v for v in VARS if row.get(f"{v}_z", 0) > C.ANOMALY_Z}
    if not hi:
        return "유량 급감(가동 중단·계측 의심)" if row.get("Q_z", 0) < -C.ANOMALY_Z else ""
    if hi == {"Q"}:
        return "유량단독급증(수리충격)"
    if {"SS", "TP"} <= hi:
        return "SS+TP 동반(고형물 유출 의심)"
    if hi in ({"TN"}, {"TN", "TOC"}):
        return "TN 상승(질소처리 저하 의심)"
    if "Q" in hi:
        return "유량+수질 동반"
    return "기타 수질 급증"


def main():
    rep = Report("10_anomaly_detection", "10. 이상치·이상 사건 탐지(v2: 해상도 하한 적용, 급증 중심)",
                 "평소 패턴을 벗어난 날을 찾고, 그 성격을 분류하며, 여러 처리장이 동시에 흔들린 광역 사건일을 추린다.")
    df = load_clean()
    sids = valid_sids(df, "TN")
    df = df[df["sid"].isin(sids)]
    skl = need("sklearn", "scikit-learn")

    events, per_sid = [], []
    for sid, g in df.groupby("sid"):
        frame = pd.DataFrame({v: daily(g, v) for v in VARS + ["pH"]})
        zs = {}
        for v in VARS:
            s = frame[v]
            a = anomaly(s, win=C.ROLL_WIN, log=True)
            mad = np.nanmedian(np.abs(a - np.nanmedian(a))) * 1.4826
            # [v2] 기록 해상도 하한: SS 0.1, TN 0.001 처럼 값이 계단식이면 MAD가 0에 가까워 과검출됨
            res = RESOLUTION.get(v)
            med = np.nanmedian(s.where(s > 0))
            floor = np.log(1 + 3 * res / med) if (res and med and med > 0) else np.log(1.05)
            mad = max(mad if (mad and not np.isnan(mad)) else 0, floor)
            z = (a - np.nanmedian(a)) / mad
            if res:   # 절대 변화가 해상도의 3배 미만이면 이상으로 보지 않음
                base = s.rolling(C.ROLL_WIN, center=True, min_periods=10).median()
                z = z.where((s - base).abs() >= 3 * res, 0)
            zs[f"{v}_z"] = z
        Z = pd.DataFrame(zs)
        flag = (Z > C.ANOMALY_Z).any(axis=1) | (Z["Q_z"] < -C.ANOMALY_Z)   # 급증 + 유량 급감만

        iso_flag = pd.Series(False, index=frame.index)
        if skl is not None:
            from sklearn.ensemble import IsolationForest
            X = np.log(frame[VARS].where(frame[VARS] > 0)).join(frame["pH"]).dropna()
            if len(X) > 200:
                Xs = (X - X.median()) / (X.quantile(0.75) - X.quantile(0.25)).replace(0, 1)
                iso = IsolationForest(n_estimators=200, contamination=0.01, random_state=C.RANDOM_STATE).fit(Xs)
                iso_flag.loc[X.index] = iso.predict(Xs) == -1

        per_sid.append({"sid": sid, "시군": g["sigun"].iloc[0], "유효일": int(frame["TN"].notna().sum()),
                        "단변량이상일": int(flag.sum()), "다변량이상일": int(iso_flag.sum()),
                        "이상일비율_pct": flag.mean() * 100,
                        **{f"{v}_급증일": int((Z[f'{v}_z'] > C.ANOMALY_Z).sum()) for v in VARS}})
        sel = Z[flag | iso_flag].copy()
        sel["iso"] = iso_flag[flag | iso_flag]
        sel["uni"] = flag[flag | iso_flag]
        sel["sid"] = sid
        sel["시군"] = g["sigun"].iloc[0]
        for v in VARS:
            sel[v] = frame.loc[sel.index, v]
        events.append(sel.reset_index().rename(columns={"index": "date"}))

    ps = pd.DataFrame(per_sid)
    ev = pd.concat(events, ignore_index=True) if events else pd.DataFrame()
    if not ev.empty:
        ev["유형"] = ev.apply(classify, axis=1)
    rep.csv(ps, "anomaly_by_sid.csv")
    rep.csv(ev, "anomaly_events_long.csv")

    rep.h("1. 개요")
    rep.kv({"분석 방류구": len(ps), "단변량 이상일 합계": int(ps["단변량이상일"].sum()),
            "다변량 이상일 합계": int(ps["다변량이상일"].sum()),
            "방류구당 이상일 비율 중앙값(%)": ps["이상일비율_pct"].median()})
    if not ev.empty:
        rep.table(ev[ev["유형"] != ""].groupby("유형").agg(사건수=("sid", "size"), 방류구수=("sid", "nunique")).reset_index()
                  .sort_values("사건수", ascending=False), "사건 유형별 건수")

    rep.h("2. 이상일이 잦은 방류구")
    rep.table(ps.sort_values("이상일비율_pct", ascending=False).head(25))

    if not ev.empty:
        rep.h("3. 광역 사건일(같은 날 이상을 보인 방류구 수)")
        day = ev.groupby("date").agg(방류구수=("sid", "nunique"),
                                     유량급증=("Q_z", lambda x: int((x > C.ANOMALY_Z).sum())),
                                     SS급증=("SS_z", lambda x: int((x > C.ANOMALY_Z).sum())),
                                     TN급증=("TN_z", lambda x: int((x > C.ANOMALY_Z).sum())),
                                     TP급증=("TP_z", lambda x: int((x > C.ANOMALY_Z).sum()))).reset_index()
        rep.csv(day, "anomaly_count_by_date.csv")
        rep.table(day.sort_values("방류구수", ascending=False).head(30))
        rep.p("유량급증이 많은 날 = 광역 강우일 후보. TN급증이 겨울에 몰리면 한파 영향 후보. 기상자료와 대조할 1순위 날짜 목록.")
        mon = ev.assign(ym=ev["date"].dt.to_period("M").astype(str)).groupby(["ym", "유형"]).size().unstack(fill_value=0).reset_index()
        rep.table(mon, "월별 사건 유형 건수", max_rows=40)

        fig, ax = plt.subplots(figsize=(13, 3.5))
        ax.bar(day["date"], day["방류구수"], width=1)
        ax.set_title("날짜별 이상 방류구 수")
        rep.fig(fig, "anomaly_count_by_date.png")

    rep.save()


if __name__ == "__main__":
    main()
