# -*- coding: utf-8 -*-
"""
06. 계절성 분석(STL 분해 + 월별 프로파일)
- 주 단위 STL(주기 52주)로 추세·계절·잔차 분해 → 계절성 강도(Fs), 추세 강도(Ft)
- 월별 정규화 프로파일 → 계절 진폭, 최고·최저 월
- 겨울(12~2월) vs 여름(6~8월) 대응 비교(Wilcoxon), 해마다 같은 계절 비교
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats
from statsmodels.tsa.seasonal import STL

import config as C
from common import Report, load_clean, valid_sids, daily

VARS = ["Q", "TOC", "SS", "TN", "TP", "pH"]


def stl_strength(s_daily):
    w = s_daily.resample("W").mean().interpolate(limit=3)
    w = w.dropna()
    if len(w) < 104:
        return np.nan, np.nan, None
    x = np.log(w) if (w > 0).all() else w
    res = STL(x, period=52, robust=True).fit()
    R, S, T = res.resid, res.seasonal, res.trend
    fs = max(0.0, 1 - np.var(R) / np.var(S + R))
    ft = max(0.0, 1 - np.var(R) / np.var(T + R))
    return fs, ft, res


def season(m):
    return {12: "겨울", 1: "겨울", 2: "겨울", 3: "봄", 4: "봄", 5: "봄",
            6: "여름", 7: "여름", 8: "여름", 9: "가을", 10: "가을", 11: "가을"}[m]


def main():
    rep = Report("06_seasonality_stl", "06. 계절성 분석(STL 분해, 월별 프로파일)",
                 "어떤 항목이 얼마나 강한 계절 주기를 갖는지, 언제 높아지는지, 처리장마다 어떻게 다른지 본다.")
    df = load_clean()
    sids = valid_sids(df, "TN", min_days=600)
    df = df[df["sid"].isin(sids)]
    rep.kv({"분석 방류구(유효 600일 이상)": len(sids)})

    rows, prof_rows = [], []
    examples = {}
    for sid, g in df.groupby("sid"):
        r = {"sid": sid, "시군": g["sigun"].iloc[0], "Q중앙": g["Q"].median()}
        for v in VARS:
            s = daily(g, v)
            fs, ft, res = stl_strength(s)
            r[f"{v}_Fs"] = fs
            r[f"{v}_Ft"] = ft
            mm = s.groupby(s.index.month).mean()
            if mm.notna().sum() >= 10 and mm.mean():
                norm = mm / mm.mean()
                r[f"{v}_진폭"] = (mm.max() - mm.min()) / mm.mean()
                r[f"{v}_최고월"] = int(mm.idxmax())
                r[f"{v}_최저월"] = int(mm.idxmin())
                for mth, val in norm.items():
                    prof_rows.append({"sid": sid, "var": v, "month": mth, "norm": val})
            if v == "TN" and res is not None and len(examples) < 6:
                examples[sid] = res
        rows.append(r)
    t = pd.DataFrame(rows)
    prof = pd.DataFrame(prof_rows)
    rep.csv(t, "seasonality_by_sid.csv")
    rep.csv(prof, "monthly_profile_long.csv")

    rep.h("1. 항목별 계절성 강도(방류구 중앙값)")
    def col(c):
        return t[c] if c in t else pd.Series(dtype=float)

    def mode_or_nan(s):
        s = s.dropna()
        return s.mode().iloc[0] if len(s) else np.nan

    s1 = pd.DataFrame([{"항목": v, "계절성강도Fs_중앙": col(f"{v}_Fs").median(),
                        "Fs>0.5 방류구비율_pct": (col(f"{v}_Fs") > 0.5).mean() * 100,
                        "추세강도Ft_중앙": col(f"{v}_Ft").median(),
                        "월진폭_중앙": col(f"{v}_진폭").median(),
                        "최고월_최빈": mode_or_nan(col(f"{v}_최고월")),
                        "최저월_최빈": mode_or_nan(col(f"{v}_최저월"))}
                       for v in VARS])
    rep.table(s1)
    rep.p("Fs(0~1): 1에 가까울수록 잔차 대비 계절 성분이 뚜렷. 최고월 최빈값이 1~2월이면 '겨울 상승형'.")

    rep.h("2. 전체 평균 월별 프로파일(연평균=1)")
    pm = prof.groupby(["var", "month"])["norm"].median().unstack("var").reset_index()
    rep.table(pm, digits=3)

    rep.h("3. 겨울 vs 여름(방류구별 대응 비교)")
    df["season"] = df["month"].map(season)
    sm = df.groupby(["sid", "season"])[VARS].median().unstack("season")
    comp = []
    for v in VARS:
        try:
            w, s_ = sm[(v, "겨울")], sm[(v, "여름")]
        except KeyError:
            continue
        ok = w.notna() & s_.notna()
        if ok.sum() < 10:
            continue
        ratio = (w[ok] / s_[ok])
        try:
            _, pv = stats.wilcoxon(w[ok], s_[ok])
        except ValueError:
            pv = np.nan
        comp.append({"항목": v, "겨울/여름_중앙": ratio.median(), "겨울>여름 방류구비율_pct": (ratio > 1).mean() * 100,
                     "Wilcoxon_p": pv, "방류구수": int(ok.sum())})
    rep.table(pd.DataFrame(comp))

    rep.h("4. 해마다 같은 계절 비교(겨울)")
    df["winter_year"] = np.where(df["month"] == 12, df["date"].dt.year + 1, df["date"].dt.year)
    wn = df[df["season"] == "겨울"].groupby(["winter_year"])[["Q", "TN", "TP", "TOC", "SS"]].median().reset_index()
    wn = wn.rename(columns={"winter_year": "겨울(1월 기준 연도)"})
    rep.table(wn, "겨울 중앙값(하수 전체)")

    rep.h("5. TN 겨울 상승이 큰 방류구")
    if "TN_진폭" in t:
        rep.table(t.sort_values("TN_진폭", ascending=False)[["sid", "시군", "Q중앙", "TN_Fs", "TN_진폭", "TN_최고월", "TN_최저월"]].head(25))

    # 그림
    hm = prof[prof["var"] == "TN"].pivot(index="sid", columns="month", values="norm")
    hm = hm.loc[hm.max(axis=1).sort_values(ascending=False).index]
    fig, ax = plt.subplots(figsize=(8, max(4, len(hm) * 0.06)))
    im = ax.imshow(hm.values, aspect="auto", cmap="RdBu_r", vmin=0.5, vmax=1.5)
    ax.set_xticks(range(12))
    ax.set_xticklabels(range(1, 13))
    ax.set_yticks([])
    ax.set_ylabel(f"방류구 {len(hm)}개(진폭 큰 순)")
    fig.colorbar(im, ax=ax, label="월평균/연평균")
    ax.set_title("TN 월별 정규화 프로파일")
    rep.fig(fig, "TN_monthly_heatmap.png")

    fig, axes = plt.subplots(2, 3, figsize=(15, 7))
    for ax, v in zip(axes.ravel(), VARS):
        d = prof[prof["var"] == v]
        data = [d.loc[d["month"] == m, "norm"].dropna() for m in range(1, 13)]
        ax.boxplot(data, showfliers=False)
        ax.axhline(1, color="gray", lw=0.6)
        ax.set_title(f"{v} 월별(연평균=1)")
    rep.fig(fig, "monthly_profile_box.png")

    for i, (sid, res) in enumerate(examples.items()):
        fig = res.plot()
        fig.set_size_inches(10, 7)
        fig.suptitle(f"STL 분해(로그 TN, 주단위): {sid}")
        rep.fig(fig, f"stl_example_{i+1}.png")

    rep.save()


if __name__ == "__main__":
    main()
