# -*- coding: utf-8 -*-
"""
04. 역산 유량 분석
- 방류구별 유량 수준, 변동성, 첨두계수(p95/p50, max/p50)
- '천장 현상': 최대치 근처에서 유량이 평평해지는 날의 비율 → 처리용량 제한 의심
- 기저유량(이동 하위 분위) 대비 초과유량 → 기상자료 없이 보는 '습윤기 민감도' 예비지표
- 도 전체 동시 고유량일 → 광역 강우일의 대리 지표(나중에 기상자료로 검증)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import config as C
from common import Report, load_clean, valid_sids, daily, wide


def main():
    rep = Report("04_flow_analysis", "04. 역산 유량 분석",
                 "배출량÷농도로 구한 일 방류유량으로 처리장의 수리학적 거동(변동, 첨두, 용량 제한, 습윤기 민감도)을 본다.")
    df = load_clean()
    sids = valid_sids(df, "Q")
    df = df[df["sid"].isin(sids)]

    rows = []
    for sid, g in df.groupby("sid"):
        q = daily(g, "Q")
        qv = q.dropna()
        p50, p95, p99, p995 = qv.quantile([0.5, 0.95, 0.99, 0.995])
        base = q.rolling(31, center=True, min_periods=10).quantile(0.10)   # 기저유량(이동 10% 분위)
        excess = (q / base - 1).dropna()
        ceiling = (qv >= 0.97 * p995).mean() * 100
        # 천장 현상: 상위 5% 일들 중 서로 2% 이내로 모인 비율
        top = qv[qv >= p95]
        plateau = (top >= top.max() * 0.98).mean() * 100 if len(top) else np.nan
        rows.append({"sid": sid, "시군": g["sigun"].iloc[0], "유효일": len(qv),
                     "Q중앙": p50, "Q평균": qv.mean(), "Q_CV": qv.std() / qv.mean(),
                     "첨두_p95/p50": p95 / p50, "첨두_max/p50": qv.max() / p50, "p99/p50": p99 / p50,
                     "1.5배초과일_pct": (qv > 1.5 * p50).mean() * 100,
                     "천장근접일_pct": ceiling, "상위5%내_평탄비율_pct": plateau,
                     "초과유량_평균_pct": excess.mean() * 100,
                     "초과유량_상위5%평균_pct": excess[excess >= excess.quantile(0.95)].mean() * 100,
                     "기저유량_계절진폭": (base.groupby(base.index.month).mean().max() /
                                     base.groupby(base.index.month).mean().min()) if base.notna().sum() > 300 else np.nan})
    st = pd.DataFrame(rows)
    rep.csv(st, "flow_stats_by_sid.csv")

    rep.h("1. 유량 변동성 개요")
    rep.table(st[["Q_CV", "첨두_p95/p50", "첨두_max/p50", "1.5배초과일_pct", "초과유량_상위5%평균_pct", "기저유량_계절진폭"]]
              .describe().T.reset_index().rename(columns={"index": "지표"}))

    rep.h("2. 습윤기 민감도 예비 순위(기상자료 없이)")
    rep.p("초과유량 = 일유량 ÷ 이동 기저유량 − 1. 상위 5% 날의 평균 초과율이 클수록 비·지하수 유입에 민감할 가능성이 크다. "
          "기상자료 결합 후 정식 I/I 지수로 대체한다.")
    rep.table(st.sort_values("초과유량_상위5%평균_pct", ascending=False)
              [["sid", "시군", "Q중앙", "Q_CV", "첨두_max/p50", "초과유량_상위5%평균_pct", "기저유량_계절진폭"]].head(30), "상위 30")

    rep.h("3. 용량 제한(천장 현상) 의심 방류구")
    rep.p("상위 5% 고유량일이 최대치 2% 이내에 몰려 있으면 유량이 물리적 상한(처리용량·펌프 능력)에 걸렸을 가능성이 있다.")
    rep.table(st.sort_values("상위5%내_평탄비율_pct", ascending=False)
              [["sid", "시군", "Q중앙", "첨두_max/p50", "상위5%내_평탄비율_pct", "천장근접일_pct"]].head(25))

    rep.h("4. 도 전체 동시 고유량일(광역 강우 대리지표)")
    w = wide(df, "Q", sids)
    cover = w.notna().mean()
    w = w.loc[:, cover[cover > 0.8].index]
    ratio = w / w.rolling(31, center=True, min_periods=10).median()
    share_high = (ratio > 1.3).sum(axis=1) / ratio.notna().sum(axis=1)
    med_ratio = ratio.median(axis=1)
    reg = pd.DataFrame({"date": ratio.index, "고유량방류구비율": share_high.values,
                        "유량비_중앙": med_ratio.values, "보고방류구": ratio.notna().sum(axis=1).values})
    rep.csv(reg, "regional_flow_signal_by_date.csv")
    top = reg.sort_values("고유량방류구비율", ascending=False).head(30)
    rep.table(top, "평소 대비 1.3배 이상 유량인 방류구 비율 상위 30일")
    rep.kv({"분석 방류구 수(보유율 80% 이상)": w.shape[1],
            "고유량방류구비율 ≥ 30%인 날 수": int((reg["고유량방류구비율"] >= 0.3).sum())})
    monthly = reg.assign(ym=reg["date"].dt.to_period("M").astype(str)).groupby("ym")["고유량방류구비율"].mean().reset_index()
    rep.table(monthly, "월별 평균 고유량 방류구 비율", max_rows=40)

    fig, ax = plt.subplots(figsize=(13, 3.5))
    ax.plot(reg["date"], reg["고유량방류구비율"] * 100, lw=0.8)
    ax.set_ylabel("%")
    ax.set_title("평소 대비 1.3배 이상 유량을 보인 방류구 비율(일별)")
    rep.fig(fig, "regional_high_flow_share.png", "솟는 날 = 광역 강우 후보일")

    # 대형 처리장 유량 시계열(정규화)
    big = st.sort_values("Q중앙", ascending=False).head(12)["sid"]
    fig, axes = plt.subplots(4, 3, figsize=(15, 10), sharex=True)
    for ax, sid in zip(axes.ravel(), big):
        q = daily(df[df["sid"] == sid], "Q")
        ax.plot(q.index, q / q.median(), lw=0.6)
        ax.set_title(sid, fontsize=9)
        ax.axhline(1, color="gray", lw=0.5)
    fig.suptitle("유량 상위 12개 방류구(중앙값=1로 정규화)")
    rep.fig(fig, "top12_flow_timeseries.png")

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.scatter(st["Q중앙"], st["첨두_max/p50"], s=10, alpha=0.6)
    ax.set_xscale("log")
    ax.set_xlabel("유량 중앙값(m3/일)")
    ax.set_ylabel("최대/중앙")
    ax.set_title("규모와 첨두계수")
    rep.fig(fig, "size_vs_peaking.png")

    rep.save()


if __name__ == "__main__":
    main()
