# -*- coding: utf-8 -*-
"""
05. 방류수 수질기준 대비 여유도와 신뢰도
- 기준 대비 비율(농도÷기준)의 분포: 중앙값, p95, 최대, 기준 80% 이상 근접일
- 대수정규분포 가정 초과확률, 신뢰도계수(CoR, Niku et al. 1979) 충족 여부
- 주의: 지역 구분(I~IV)과 기준값은 config.py 에서 반드시 확인·수정하세요.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats

import config as C
from common import Report, load_clean, valid_sids

Z95 = stats.norm.ppf(0.95)


def cor(cv, z=Z95):
    """신뢰도계수: 평균 농도가 기준×CoR 이하이면 해당 신뢰수준으로 기준 준수"""
    s2 = np.log(cv ** 2 + 1)
    return np.sqrt(cv ** 2 + 1) * np.exp(-z * np.sqrt(s2))


def main():
    rep = Report("05_compliance_margin", "05. 방류수 수질기준 대비 여유도와 신뢰도",
                 "처리장이 기준을 얼마나 여유 있게 지키는지, 얼마나 '안정적으로' 지키는지를 비교한다.")
    df = load_clean()
    df = df[df["sid"].isin(valid_sids(df, "TN"))]
    for p in C.PARAMS:   # 이전 버전 tms_clean.pkl 호환
        if f"std_{p}" not in df:
            df[f"std_{p}"] = np.nan
    n_unknown = int(df.groupby("sid")["region"].first().isna().sum())
    df["region"] = df["region"].fillna(C.DEFAULT_REGION)
    rep.kv({"지역 정보 없는 방류구(기본 지역 적용)": n_unknown})
    rep.p(f"⚠ 지역 정보가 없는 방류구는 '{C.DEFAULT_REGION}' 지역 기준을 적용했다. "
          f"기준값: {C.DISCHARGE_STANDARDS}. 결과 해석 전 기준·지역을 꼭 확인할 것.")

    rows = []
    for sid, g in df.groupby("sid"):
        reg = g["region"].iloc[0]
        std = dict(C.DISCHARGE_STANDARDS.get(reg, C.DISCHARGE_STANDARDS[C.DEFAULT_REGION]))
        for p in C.PARAMS:   # [v2] site_region.csv 의 std_TOC 등 개별 기준값이 있으면 우선
            if f"std_{p}" in g and pd.notna(g[f"std_{p}"].iloc[0]):
                std[p] = float(g[f"std_{p}"].iloc[0])
        r = {"sid": sid, "시군": g["sigun"].iloc[0], "지역": reg, "Q중앙": g["Q"].median()}
        for p in C.PARAMS:
            x = g[p].dropna()
            x = x[x > 0]
            if len(x) < 30:
                continue
            ratio = x / std[p]
            cv = x.std() / x.mean()
            mu, sg = np.log(x).mean(), np.log(x).std()
            r[f"{p}_비율중앙"] = ratio.median()
            r[f"{p}_비율p95"] = ratio.quantile(0.95)
            r[f"{p}_비율최대"] = ratio.max()
            r[f"{p}_초과일"] = int((ratio > 1).sum())
            r[f"{p}_80%근접일"] = int((ratio > 0.8).sum())
            r[f"{p}_대수정규초과확률_pct"] = (1 - stats.norm.cdf((np.log(std[p]) - mu) / sg)) * 100 if sg > 0 else 0
            r[f"{p}_CoR"] = cor(cv)
            r[f"{p}_평균/(기준×CoR)"] = x.mean() / (std[p] * cor(cv))
        rows.append(r)
    t = pd.DataFrame(rows)
    rep.csv(t, "compliance_by_sid.csv")

    rep.h("1. 항목별 요약(하수 방류구)")
    summ = []
    for p in C.PARAMS:
        if f"{p}_비율중앙" not in t:
            continue
        summ.append({"항목": p,
                     "기준대비_중앙의중앙": t[f"{p}_비율중앙"].median(),
                     "p95비율>0.8 방류구": int((t[f"{p}_비율p95"] > 0.8).sum()),
                     "초과일 있는 방류구": int((t[f"{p}_초과일"] > 0).sum()),
                     "CoR 미충족(>1) 방류구": int((t[f"{p}_평균/(기준×CoR)"] > 1).sum()),
                     "분석 방류구": int(t[f"{p}_비율중앙"].notna().sum())})
    rep.table(pd.DataFrame(summ))
    rep.p("해석 포인트: 어떤 항목이 기준에 가장 '빠듯한지'(binding constraint). 보통 TP 또는 TN이 될 것으로 예상.")

    rep.h("2. 여유가 가장 적은 방류구")
    for p in C.PARAMS:
        c = f"{p}_비율p95"
        if c in t:
            rep.table(t.sort_values(c, ascending=False)[["sid", "시군", "지역", "Q중앙", f"{p}_비율중앙", c, f"{p}_비율최대",
                                                          f"{p}_80%근접일", f"{p}_초과일", f"{p}_평균/(기준×CoR)"]].head(15),
                      f"{p}: 기준 대비 p95 비율 상위 15")

    rep.h("3. 월별 기준 근접(하수 전체)")
    df["std_TN"] = df["std_TN"].fillna(df["region"].map(lambda r: C.DISCHARGE_STANDARDS.get(r, C.DISCHARGE_STANDARDS[C.DEFAULT_REGION])["TN"]))
    df["std_TP"] = df["std_TP"].fillna(df["region"].map(lambda r: C.DISCHARGE_STANDARDS.get(r, C.DISCHARGE_STANDARDS[C.DEFAULT_REGION])["TP"]))
    df["TN_r"] = df["TN"] / df["std_TN"]
    df["TP_r"] = df["TP"] / df["std_TP"]
    m = df.groupby("month").agg(TN비율_중앙=("TN_r", "median"), TN비율_p95=("TN_r", lambda x: x.quantile(.95)),
                                TN_80근접_pct=("TN_r", lambda x: (x > .8).mean() * 100),
                                TP비율_중앙=("TP_r", "median"), TP비율_p95=("TP_r", lambda x: x.quantile(.95)),
                                TP_80근접_pct=("TP_r", lambda x: (x > .8).mean() * 100)).reset_index()
    rep.table(m, "월별 기준 대비 비율")
    rep.p("겨울철 TN 근접 증가 여부 → 저수온 취약성 연구(주제 C)의 근거.")

    fig, axes = plt.subplots(1, 4, figsize=(15, 4))
    for ax, p in zip(axes, C.PARAMS):
        c = f"{p}_비율p95"
        if c in t:
            ax.hist(t[c].dropna(), bins=30)
            ax.axvline(1, color="red", lw=1)
            ax.axvline(0.8, color="orange", lw=1, ls="--")
            ax.set_title(f"{p} 기준 대비 p95 비율")
    rep.fig(fig, "ratio_p95_hist.png", "빨강=기준, 주황=80%")

    rep.save()


if __name__ == "__main__":
    main()
