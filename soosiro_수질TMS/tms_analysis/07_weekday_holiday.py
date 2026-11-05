# -*- coding: utf-8 -*-
"""
07. 요일·공휴일·명절 효과
- 요일별 정규화 프로파일(유량·부하·농도), 주말/평일 비, 방류구별 Kruskal-Wallis
- 명절 연휴 동안의 유량·부하 변화율(앞뒤 2주 같은 요일 대비)
  → 도시형(감소)과 귀성·관광형(증가) 처리구역 구분: 하수량을 '생활인구'의 지표로 읽기
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats

import config as C
from common import Report, load_clean, valid_sids, daily

DOW = ["월", "화", "수", "목", "금", "토", "일"]
VARS = ["Q", "TN_load", "TP_load", "TOC_load", "TN", "TP", "TOC"]


def main():
    rep = Report("07_weekday_holiday", "07. 요일·공휴일·명절 효과",
                 "사람의 생활 주기가 하수량과 방류 부하에 얼마나 드러나는지 보고, 명절 인구이동을 처리장 단위로 정량화한다.")
    df = load_clean()
    sids = valid_sids(df, "Q")
    df = df[df["sid"].isin(sids)].copy()

    # 계절 영향 제거: 31일 이동 중앙값으로 나눈 비율
    for v in VARS:
        df[f"{v}_r"] = np.nan
    parts = []
    for sid, g in df.groupby("sid"):
        g = g.sort_values("date").copy()
        for v in VARS:
            s = daily(g, v)
            base = s.rolling(31, center=True, min_periods=10).median()
            r = (s / base).reindex(g["date"]).values
            g[f"{v}_r"] = r
        parts.append(g)
    df = pd.concat(parts)
    work = df[~df["is_holiday"]]

    rep.h("1. 요일별 프로파일(31일 이동중앙값 대비, 공휴일 제외, 방류구 중앙값)")
    prof = work.groupby(["sid", "dow"])[[f"{v}_r" for v in VARS]].median()
    pm = prof.groupby("dow").median()
    pm.index = [DOW[i] for i in pm.index]
    pm.columns = VARS
    rep.table(pm.reset_index().rename(columns={"index": "요일"}), digits=3)

    rows = []
    for sid, g in work.groupby("sid"):
        r = {"sid": sid, "시군": g["sigun"].iloc[0], "Q중앙": g["Q"].median()}
        for v in ["Q", "TN_load", "TN"]:
            x = g[f"{v}_r"]
            wk, we = x[g["dow"] < 5].median(), x[g["dow"] >= 5].median()
            r[f"{v}_주말/평일"] = we / wk if wk else np.nan
            groups = [x[g["dow"] == d].dropna() for d in range(7)]
            if all(len(gr) > 10 for gr in groups):
                r[f"{v}_요일KW_p"] = stats.kruskal(*groups).pvalue
            dmed = g.groupby("dow")[f"{v}_r"].median()
            r[f"{v}_요일진폭"] = dmed.max() - dmed.min()
            r[f"{v}_최대요일"] = DOW[int(dmed.idxmax())] if dmed.notna().any() else ""
        rows.append(r)
    t = pd.DataFrame(rows)
    rep.csv(t, "weekday_by_sid.csv")

    rep.h("2. 주말/평일 비 분포")
    rep.table(t[["Q_주말/평일", "TN_load_주말/평일", "TN_주말/평일", "Q_요일진폭"]].describe().T.reset_index()
              .rename(columns={"index": "지표"}))
    rep.kv({"요일 효과 유의(p<0.01) 방류구 비율_Q(%)": (t["Q_요일KW_p"] < 0.01).mean() * 100 if "Q_요일KW_p" in t else np.nan})
    rep.table(t.sort_values("Q_주말/평일", ascending=False)[["sid", "시군", "Q중앙", "Q_주말/평일", "Q_최대요일"]].head(15),
              "주말에 유량이 늘어나는 방류구(관광·주거형 후보)")
    rep.table(t.sort_values("Q_주말/평일")[["sid", "시군", "Q중앙", "Q_주말/평일", "Q_최대요일"]].head(15),
              "주말에 유량이 줄어드는 방류구(업무·산업형 후보)")

    rep.h("3. 명절 효과")
    hrows = []
    for name, (s, e) in C.MAJOR_HOLIDAYS.items():
        s, e = pd.Timestamp(s), pd.Timestamp(e)
        if s > df["date"].max() or e < df["date"].min():
            continue
        hol_mask = (df["date"] >= s) & (df["date"] <= e)
        ref_mask = (((df["date"] >= s - pd.Timedelta(days=14)) & (df["date"] < s - pd.Timedelta(days=2))) |
                    ((df["date"] > e + pd.Timedelta(days=2)) & (df["date"] <= e + pd.Timedelta(days=14)))) & ~df["is_holiday"]
        for sid, g in df.groupby("sid"):
            h = g.loc[hol_mask.loc[g.index], ["Q", "TN_load", "TP_load"]].mean()
            rf = g.loc[ref_mask.loc[g.index], ["Q", "TN_load", "TP_load"]].mean()
            hrows.append({"명절": name, "sid": sid, "시군": g["sigun"].iloc[0], "Q중앙": g["Q"].median(),
                          "Q변화_pct": (h["Q"] / rf["Q"] - 1) * 100 if rf["Q"] else np.nan,
                          "TN부하변화_pct": (h["TN_load"] / rf["TN_load"] - 1) * 100 if rf["TN_load"] else np.nan,
                          "TP부하변화_pct": (h["TP_load"] / rf["TP_load"] - 1) * 100 if rf["TP_load"] else np.nan})
    ht = pd.DataFrame(hrows)
    rep.csv(ht, "holiday_effect_long.csv")
    if len(ht):
        rep.table(ht.groupby("명절")[["Q변화_pct", "TN부하변화_pct", "TP부하변화_pct"]].median().reset_index(),
                  "명절별 변화율(방류구 중앙값)")
        avg = ht.groupby(["sid", "시군"], dropna=False)[["Q변화_pct", "TN부하변화_pct"]].mean().reset_index()
        cons = ht.groupby("sid")["Q변화_pct"].apply(lambda x: max((x > 0).mean(), (x < 0).mean()))
        avg["일관성(같은부호 비율)"] = avg["sid"].map(cons)
        rep.table(avg.sort_values("Q변화_pct", ascending=False).head(20), "명절에 유량이 느는 방류구(귀성·관광형 후보)")
        rep.table(avg.sort_values("Q변화_pct").head(20), "명절에 유량이 주는 방류구(도시·산업형 후보)")
        if avg["시군"].notna().any():
            rep.table(avg.groupby("시군")[["Q변화_pct", "TN부하변화_pct"]].median().sort_values("Q변화_pct").reset_index(),
                      "시군별 명절 유량 변화(중앙값)")
        rep.p("주의: 명절 기간 강우가 있었다면 유량 증가가 섞인다. 기상자료 결합 후 강우일을 빼고 다시 확인.")

    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    for ax, v in zip(axes, ["Q", "TN_load", "TN"]):
        d = prof[f"{v}_r"].unstack("dow")
        ax.boxplot([d[i].dropna() for i in range(7)], showfliers=False)
        ax.set_xticks(range(1, 8))
        ax.set_xticklabels(DOW)
        ax.axhline(1, color="gray", lw=0.6)
        ax.set_title(f"{v} 요일별(이동중앙값=1)")
    rep.fig(fig, "weekday_profile_box.png")

    if len(ht):
        fig, ax = plt.subplots(figsize=(8, 4))
        names = ht["명절"].unique()
        ax.boxplot([ht.loc[ht["명절"] == n, "Q변화_pct"].dropna() for n in names], showfliers=False)
        ax.set_xticks(range(1, len(names) + 1))
        ax.set_xticklabels(names)
        ax.axhline(0, color="gray", lw=0.6)
        ax.set_ylabel("유량 변화(%)")
        ax.set_title("명절 연휴 유량 변화(앞뒤 2주 대비)")
        rep.fig(fig, "holiday_flow_change.png")

    rep.save()


if __name__ == "__main__":
    main()
