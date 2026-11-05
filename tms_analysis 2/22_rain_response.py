# -*- coding: utf-8 -*-
"""
22. 강우 반응 분석(연구질문 RQ3 + RQ1·RQ2·RQ4 보조) — 21번 산출물 필요
1) 건기 기저유량 대비 초과유량 → 강우 민감도(I/I 지수): 강수 10mm당 유량 증가율(%), 회귀 R²
2) 강우 이벤트(일강수 ≥ EVENT_MM)별 첨두 초과율·회복일수
3) 느린 침입수 지표: 장마 후(8~9월) 건기 기저유량 ÷ 봄(4~5월) 건기 기저유량
4) 용량 천장: 큰 비(≥50mm) 날 유량이 전체 최대치 근처에서 평평해지는 비율, 시설용량 대비(있으면)
5) 비 온 날 vs 건기 수질 비(C-Q 이벤트판), TP 여름 상승이 건기에도 남는지(RQ2)
6) 명절 효과를 건기일만으로 다시 계산(RQ4)
7) 분류식 비율(sigun_sewer.csv), 12번 공통신호 R²와의 관계(RQ1)
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


def ols(y, X):
    m = np.isfinite(y) & np.isfinite(X).all(axis=1)
    if m.sum() < 60:
        return None, np.nan
    Xm = np.column_stack([np.ones(m.sum()), X[m]])
    beta, *_ = np.linalg.lstsq(Xm, y[m], rcond=None)
    pred = Xm @ beta
    r2 = 1 - ((y[m] - pred) ** 2).sum() / ((y[m] - y[m].mean()) ** 2).sum()
    return beta, r2


def main():
    rep = Report("22_rain_response", "22. 강우 반응 분석(I/I·용량 천장·비 온 날 수질)",
                 "비가 처리장 유량과 수질을 얼마나, 얼마 동안, 어떤 방식으로 바꾸는지 처리장별로 정량화한다.")
    if not C.WEATHER_PKL.exists():
        rep.p("⏳ 자료 대기: 먼저 21_merge_weather.py 를 실행하세요(기상자료 필요).")
        rep.save()
        return
    df = load_clean()
    df = df[df["sid"].isin(valid_sids(df, "Q"))]
    wx = pd.read_pickle(C.WEATHER_PKL)
    df = df.merge(wx, on=["site", "date"], how="left")
    rep.kv({"분석 방류구": df["sid"].nunique(), "기상 결합률(%)": df["rain_mm"].notna().mean() * 100})

    rows, ev_rows = [], []
    for sid, g in df.groupby("sid"):
        g = g.set_index("date").sort_index().asfreq("D")
        q = g["Q"]
        qd = q.where(g["dry"] == True)  # noqa: E712
        base = qd.rolling(31, center=True, min_periods=8).median().interpolate(limit_direction="both")
        ex = q / base - 1
        rain = g["rain_mm"].fillna(0)
        X = np.column_stack([rain.values, rain.shift(1).fillna(0).values, rain.shift(2).fillna(0).values])
        beta, r2 = ols(ex.values, X)
        r = {"sid": sid, "site": g["site"].dropna().iloc[0], "시군": g["sigun"].dropna().iloc[0] if g["sigun"].notna().any() else np.nan,
             "Q중앙": q.median(), "건기일수": int(g["dry"].sum())}
        if beta is not None:
            r["당일10mm당_증가pct"] = beta[1] * 10 * 100
            r["3일누적10mm당_증가pct"] = (beta[1] + beta[2] + beta[3]) * 10 * 100
            r["강우회귀_R2"] = r2
        # 이벤트
        ev_days = rain[rain >= C.EVENT_MM].index
        peaks, recs = [], []
        last = None
        for d0 in ev_days:
            if last is not None and (d0 - last).days <= 3:
                continue
            last = d0
            win = ex.loc[d0:d0 + pd.Timedelta(days=3)]
            if win.notna().sum() == 0:
                continue
            pk = win.max()
            after = ex.loc[d0:d0 + pd.Timedelta(days=30)]
            below = after[after < 0.1]
            rec = (below.index[0] - d0).days if len(below) else 30
            peaks.append(pk)
            recs.append(rec)
            ev_rows.append({"sid": sid, "date": d0, "강수mm": rain.loc[d0], "3일강수mm": rain.loc[d0:d0 + pd.Timedelta(days=2)].sum(),
                            "첨두초과_pct": pk * 100, "회복일": rec})
        r["이벤트수"] = len(peaks)
        r["이벤트_첨두초과_중앙pct"] = np.median(peaks) * 100 if peaks else np.nan
        r["이벤트_회복일_중앙"] = np.median(recs) if recs else np.nan
        # 느린 침입수
        ratios = []
        for y in sorted(set(g.index.year)):
            spring = qd[(qd.index.year == y) & qd.index.month.isin([4, 5])].median()
            post = qd[(qd.index.year == y) & qd.index.month.isin([8, 9])].median()
            if spring and post and np.isfinite(spring) and np.isfinite(post):
                ratios.append(post / spring)
        r["장마후/봄_건기기저비"] = np.mean(ratios) if ratios else np.nan
        # 용량 천장
        heavy = rain >= 50
        qmax = q.quantile(0.995)
        r["큰비일수(≥50mm)"] = int(heavy.sum())
        r["큰비일_천장근접비율_pct"] = ((q[heavy] >= 0.97 * qmax).mean() * 100) if heavy.sum() else np.nan
        r["큰비일_유량/평소"] = (q[heavy] / base[heavy]).median() if heavy.sum() else np.nan
        # 비 온 날 vs 건기 수질
        wet = g["rain_3d"] >= 10
        dry = g["dry"] == True  # noqa: E712
        for p in C.PARAMS:
            a, b = g.loc[wet, p].dropna(), g.loc[dry, p].dropna()
            if len(a) > 10 and len(b) > 30:
                r[f"{p}_강우/건기"] = a.median() / b.median() if b.median() else np.nan
                r[f"{p}_강우건기_p"] = stats.mannwhitneyu(a, b).pvalue
        # TP 여름 상승이 건기에도 남는가
        summer = g.index.month.isin([6, 7, 8, 9])
        winter = g.index.month.isin([12, 1, 2])
        tp_all = g.loc[summer, "TP"].median() / g.loc[winter, "TP"].median()
        tp_dry = g.loc[summer & dry, "TP"].median() / g.loc[winter & dry, "TP"].median()
        r["TP_여름/겨울_전체"] = tp_all
        r["TP_여름/겨울_건기만"] = tp_dry
        # 명절(건기일만)
        hch = []
        for name, (s, e) in C.MAJOR_HOLIDAYS.items():
            s, e = pd.Timestamp(s), pd.Timestamp(e)
            hol = (g.index >= s) & (g.index <= e) & dry
            ref = (((g.index >= s - pd.Timedelta(days=14)) & (g.index < s - pd.Timedelta(days=2))) |
                   ((g.index > e + pd.Timedelta(days=2)) & (g.index <= e + pd.Timedelta(days=14)))) & dry
            if hol.sum() >= 1 and ref.sum() >= 5:
                hch.append(q[hol].mean() / q[ref].mean() - 1)
        r["명절_건기_유량변화pct"] = np.mean(hch) * 100 if hch else np.nan
        rows.append(r)
    t = pd.DataFrame(rows)
    ev = pd.DataFrame(ev_rows)

    if C.SITE_FACILITY_CSV.exists():
        fac = pd.read_csv(C.SITE_FACILITY_CSV, encoding="utf-8-sig")
        if "capacity_m3d" in fac:
            cap = fac.groupby("site")["capacity_m3d"].sum()
            t["시설용량"] = t["site"].map(cap)
            t["평상가동률_pct"] = t["Q중앙"] / t["시설용량"] * 100
    rep.csv(t, "rain_response_by_sid.csv")
    rep.csv(ev, "rain_events_long.csv")

    rep.h("1. 강우 민감도(I/I 지수) 분포")
    cols = ["당일10mm당_증가pct", "3일누적10mm당_증가pct", "강우회귀_R2", "이벤트_첨두초과_중앙pct", "이벤트_회복일_중앙", "장마후/봄_건기기저비"]
    rep.table(t[cols].describe().T.reset_index().rename(columns={"index": "지표"}), digits=2)
    rep.table(t.sort_values("3일누적10mm당_증가pct", ascending=False)
              [["sid", "시군", "Q중앙", "3일누적10mm당_증가pct", "강우회귀_R2", "이벤트_첨두초과_중앙pct", "이벤트_회복일_중앙"]].head(30),
              "강우 민감도 상위 30", digits=2)
    rep.table(t.sort_values("장마후/봄_건기기저비", ascending=False)[["sid", "시군", "장마후/봄_건기기저비", "이벤트_회복일_중앙"]].head(20),
              "느린 침입수(지하수) 의심 상위 20", digits=3)

    rep.h("2. 용량 천장(큰 비에도 유량이 더 오르지 않음)")
    cc = ["sid", "시군", "Q중앙", "큰비일수(≥50mm)", "큰비일_천장근접비율_pct", "큰비일_유량/평소"] + (["시설용량", "평상가동률_pct"] if "시설용량" in t else [])
    rep.table(t[t["큰비일수(≥50mm)"] > 0].sort_values("큰비일_천장근접비율_pct", ascending=False)[cc].head(25), digits=2)
    rep.p("큰 비 날 천장근접비율이 높고 '유량/평소'가 낮으면(예: 1.1 미만) 처리용량을 넘는 하수가 다른 경로로 나갔을 가능성.")

    rep.h("3. 비 온 날 vs 건기 수질(중앙값 비)")
    s3 = []
    for p in C.PARAMS:
        c = f"{p}_강우/건기"
        if c in t:
            s3.append({"항목": p, "비_중앙": t[c].median(), "강우시 높아짐(>1.1) 방류구": int((t[c] > 1.1).sum()),
                       "강우시 낮아짐(<0.9) 방류구": int((t[c] < 0.9).sum()), "유의(p<0.01) 방류구": int((t[f"{p}_강우건기_p"] < 0.01).sum())})
    rep.table(pd.DataFrame(s3), digits=3)

    rep.h("4. TP 여름 상승은 건기에도 남는가(RQ2)")
    rep.kv({"TP 여름/겨울(전체일) 중앙": t["TP_여름/겨울_전체"].median(),
            "TP 여름/겨울(건기일만) 중앙": t["TP_여름/겨울_건기만"].median(),
            "건기에도 여름이 10% 이상 높은 방류구": int((t["TP_여름/겨울_건기만"] > 1.1).sum())})
    rep.p("건기일만으로도 여름 상승이 유지되면 강우(수리) 요인보다 수온·공정 요인이 크다는 근거가 된다.")

    rep.h("5. 명절 효과(건기일만, RQ4)")
    if t["시군"].notna().any():
        rep.table(t.groupby("시군")["명절_건기_유량변화pct"].median().sort_values().reset_index(), digits=2)

    rep.h("6. 강우 민감도를 설명하는 요인(RQ1)")
    f12 = C.RESULTS_DIR / "12_cross_site_sync" / "Q_pca_r2.csv"
    if f12.exists():
        p12 = pd.read_csv(f12)
        j = t.merge(p12[["sid", "PC1_R2"]], on="sid")
        rep.kv({"Spearman(강우 민감도 vs 유량 공통신호 R²)": j["3일누적10mm당_증가pct"].corr(j["PC1_R2"], method="spearman")})
    rep.kv({"Spearman(강우 민감도 vs log 규모)": t["3일누적10mm당_증가pct"].corr(np.log(t["Q중앙"]), method="spearman")})
    if C.SIGUN_SEWER_CSV.exists():
        sw = pd.read_csv(C.SIGUN_SEWER_CSV, encoding="utf-8-sig")
        if "separate_sewer_pct" in sw:
            j = t.merge(sw[["sigun", "separate_sewer_pct"]], left_on="시군", right_on="sigun", how="left")
            rep.kv({"Spearman(강우 민감도 vs 시군 분류식 비율)": j["3일누적10mm당_증가pct"].corr(j["separate_sewer_pct"], method="spearman")})
            rep.p("음의 상관이면 '합류식 비율이 높을수록 비에 민감'이라는 가설을 지지.")
    else:
        rep.p("sigun_sewer.csv 가 없어 분류식 비율과의 관계는 건너뜀.")

    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    ax.scatter(t["Q중앙"], t["3일누적10mm당_증가pct"], s=12, alpha=0.6)
    ax.set_xscale("log")
    ax.set_xlabel("유량 중앙값(m3/일)")
    ax.set_ylabel("3일 누적 10mm당 유량 증가(%)")
    ax.set_title("처리장 규모와 강우 민감도")
    rep.fig(fig, "size_vs_rain_sensitivity.png")

    rep.save()


if __name__ == "__main__":
    main()
