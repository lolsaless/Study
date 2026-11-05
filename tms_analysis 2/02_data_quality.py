# -*- coding: utf-8 -*-
"""
02. 자료품질 진단(QA/QC)
- 방류구별 결측률, 0값, 고정값(flat-line) 구간, 값의 해상도(반올림 단위), 급변 이상치, 고유값 비율
- 품질점수(0~100)와 등급(A~D) 부여 → 이후 분석에서 품질 낮은 방류구를 거를 기준
- 날짜별 '보고 방류구 수' → 시스템 전체 중단일 탐지
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import config as C
from common import Report, load_clean, robust_z, daily


def longest_run_and_share(s: pd.Series, min_run: int):
    """연속으로 같은 값이 이어지는 최장 길이와, min_run 이상 구간에 속한 날의 비율"""
    x = s.dropna()
    if len(x) < 2:
        return np.nan, np.nan
    grp = (x != x.shift()).cumsum()
    runs = x.groupby(grp).size()
    longest = runs.max()
    share = runs[runs >= min_run].sum() / len(x)
    return longest, share


def resolution(s: pd.Series):
    """값들 사이 최소 양의 간격 ≈ 기록 해상도"""
    u = np.sort(s.dropna().unique())
    if len(u) < 3:
        return np.nan
    d = np.diff(u)
    d = d[d > 1e-9]
    return float(np.round(d.min(), 6)) if len(d) else np.nan


def main():
    rep = Report("02_data_quality", "02. 자료품질 진단(QA/QC)",
                 "센서 고장·미전송·대체값 등 자료 품질 문제를 정량화하고, 방류구별 품질점수를 만든다.")
    df = load_clean(types=None)
    params = C.PARAMS + ["pH"]

    rows = []
    for sid, g in df.groupby("sid"):
        g = g.sort_values("date")
        span = (g["date"].max() - g["date"].min()).days + 1
        r = {"sid": sid, "사업장": g["site"].iloc[0], "유형": g["site_type"].iloc[0],
             "시작": g["date"].min(), "끝": g["date"].max(), "기간일수": span, "보고일수": len(g),
             "날짜누락_pct": (1 - len(g) / span) * 100, "전항목0_pct": g["all_zero"].mean() * 100}
        flat_shares, miss = [], []
        for p in params:
            s = g[p]
            miss.append(s.isna().mean() * 100)
            r[f"{p}_결측pct"] = s.isna().mean() * 100
            lr, sh = longest_run_and_share(s, C.FLATLINE_MIN_RUN)
            r[f"{p}_최장고정일"] = lr
            r[f"{p}_고정구간pct"] = sh * 100 if pd.notna(sh) else np.nan
            flat_shares.append(r[f"{p}_고정구간pct"])
            r[f"{p}_고유값비"] = s.nunique() / max(s.notna().sum(), 1)
            r[f"{p}_해상도"] = resolution(s)
            if p != "pH":
                z = robust_z(np.log(s.where(s > 0)))
                r[f"{p}_급변pct"] = (z.abs() > C.SPIKE_Z).mean() * 100
        r["평균결측pct"] = np.nanmean(miss)
        r["평균고정구간pct"] = np.nanmean(flat_shares)
        r["평균급변pct"] = np.nanmean([r[f"{p}_급변pct"] for p in C.PARAMS])
        r["Q_TN_TOC상대차"] = g["Q_gap_TN_TOC"].median()
        rows.append(r)
    q = pd.DataFrame(rows)

    # 품질점수: 100에서 감점(가중치는 연구 초기값. 필요시 조정)
    pen = (0.5 * q["평균결측pct"].clip(0, 100)
           + 0.4 * q["평균고정구간pct"].fillna(0).clip(0, 100)
           + 0.3 * q["날짜누락_pct"].clip(0, 100)
           + 2.0 * q["평균급변pct"].fillna(0).clip(0, 20)
           + 10 * (q["Q_TN_TOC상대차"].fillna(0) > 0.05))
    q["품질점수"] = (100 - pen).clip(0, 100).round(1)
    q["등급"] = pd.cut(q["품질점수"], [-1, 60, 75, 90, 101], labels=["D", "C", "B", "A"]).astype(str)
    rep.p("품질점수 = 100 − (0.5×평균결측% + 0.4×평균고정구간% + 0.3×날짜누락% + 2×평균급변%(최대20) + TN·TOC 역산유량 불일치 시 10). "
          "가중치는 초기값이며 결과를 보고 조정한다.")

    rep.h("1. 등급 분포")
    rep.table(q.groupby(["유형", "등급"]).size().unstack(fill_value=0).reset_index(), "유형 × 등급 방류구 수")
    rep.kv({"전체 품질점수 중앙값": q["품질점수"].median(),
            "A등급 비율(%)": (q["등급"] == "A").mean() * 100,
            "D등급 방류구 수": int((q["등급"] == "D").sum())})

    rep.h("2. 항목별 품질 문제 요약(방류구 중앙값)")
    summ = []
    for p in params:
        summ.append({"항목": p,
                     "결측%_중앙": q[f"{p}_결측pct"].median(),
                     "고정구간%_중앙": q[f"{p}_고정구간pct"].median(),
                     "고정구간≥20%인 방류구수": int((q[f"{p}_고정구간pct"] >= 20).sum()),
                     "최장고정일_최대": q[f"{p}_최장고정일"].max(),
                     "해상도_최빈": q[f"{p}_해상도"].mode().iloc[0] if q[f"{p}_해상도"].notna().any() else np.nan,
                     "급변%_중앙": q[f"{p}_급변pct"].median() if f"{p}_급변pct" in q else np.nan})
    rep.table(pd.DataFrame(summ), "항목별 요약")

    rep.h("3. 품질이 낮은 방류구")
    cols = ["sid", "유형", "품질점수", "등급", "평균결측pct", "평균고정구간pct", "날짜누락_pct", "평균급변pct",
            "SS_최장고정일", "TP_최장고정일", "Q_TN_TOC상대차"]
    rep.table(q.sort_values("품질점수")[cols].head(30), "하위 30")
    rep.table(q.sort_values("SS_고정구간pct", ascending=False)[["sid", "유형", "SS_고정구간pct", "SS_최장고정일", "SS_고유값비", "SS_해상도"]].head(20),
              "SS 고정값이 심한 방류구(상위 20)")
    rep.csv(q, "quality_by_sid.csv")

    rep.h("4. 날짜별 보고 현황(시스템 중단일 탐지)")
    per_day = df.groupby("date").agg(보고방류구=("sid", "nunique"),
                                    TN유효=("TN", "count"),
                                    전항목0=("all_zero", "sum")).reset_index()
    base = per_day["TN유효"].rolling(15, center=True, min_periods=5).median()
    per_day["TN유효_기준대비"] = per_day["TN유효"] / base
    low = per_day[per_day["TN유효_기준대비"] < 0.85].sort_values("TN유효_기준대비")
    rep.table(low.head(30), "TN 유효 방류구 수가 평소보다 15% 이상 적은 날")
    rep.csv(per_day, "reporting_by_date.csv")

    fig, ax = plt.subplots(figsize=(12, 3.5))
    ax.plot(per_day["date"], per_day["TN유효"], lw=0.8)
    ax.set_title("날짜별 TN 유효 방류구 수")
    ax.set_ylabel("방류구 수")
    rep.fig(fig, "reporting_by_date.png", "급감한 날 = 시스템·통신 문제 가능성")

    # 월별 품질 히트맵(하위 60개 방류구)
    worst = q.sort_values("품질점수").head(60)["sid"]
    hm = (df[df["sid"].isin(worst)].assign(ok=lambda d: d["TN"].notna())
            .pivot_table(index="sid", columns="ym", values="ok", aggfunc="mean"))
    fig, ax = plt.subplots(figsize=(14, max(4, len(hm) * 0.18)))
    im = ax.imshow(hm.values, aspect="auto", cmap="viridis", vmin=0, vmax=1)
    ax.set_yticks(range(len(hm)))
    ax.set_yticklabels(hm.index, fontsize=6)
    ax.set_xticks(range(len(hm.columns)))
    ax.set_xticklabels(hm.columns, rotation=90, fontsize=7)
    fig.colorbar(im, ax=ax, label="TN 유효 비율")
    ax.set_title("품질 하위 60개 방류구의 월별 TN 유효 비율")
    rep.fig(fig, "worst_sites_monthly_validity.png")

    fig, ax = plt.subplots(figsize=(6, 3.5))
    ax.hist(q["품질점수"], bins=30)
    ax.set_xlabel("품질점수")
    ax.set_ylabel("방류구 수")
    rep.fig(fig, "quality_score_hist.png")

    rep.save()


if __name__ == "__main__":
    main()
