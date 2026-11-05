# -*- coding: utf-8 -*-
"""
23. 기온-수질 관계와 임계기온(연구질문 RQ2) — 21번 산출물 필요
- 강우 영향을 피하려고 '건기일'만 사용
- TN: 몇 ℃ 이하에서 오르기 시작하는가 → 꺾인선 회귀(구간회귀)로 임계기온·기울기 추정
  log TN = a + b1·min(T−Tc, 0) + b2·max(T−Tc, 0),  Tc = 0~20℃ 격자 탐색
- 기온 이동평균 창(7·14·30일) 중 가장 잘 맞는 창 = 공정 반응 지연(관성)의 간접 지표
- TP: 기온이 오를수록 오르는가(여름 상승의 수온 가설) — 기울기와 유량 통제 편상관
- 처리공법(site_facility.csv 의 process)이 있으면 공법별 임계기온 비교
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

GRID = np.arange(0, 20.5, 0.5)


def seg_fit(T, y):
    """꺾인선 회귀. 반환: Tc, b_low, b_high, R2, ΔBIC(직선 대비, 음수면 꺾인선이 더 좋음)"""
    m = np.isfinite(T) & np.isfinite(y)
    T, y = T[m], y[m]
    n = len(y)
    if n < 100:
        return [np.nan] * 5
    sst = ((y - y.mean()) ** 2).sum()
    X1 = np.column_stack([np.ones(n), T])
    b1, *_ = np.linalg.lstsq(X1, y, rcond=None)
    sse1 = ((y - X1 @ b1) ** 2).sum()
    best = (np.inf, None, None)
    for tc in GRID:
        if (T < tc).sum() < 20 or (T >= tc).sum() < 20:
            continue
        X = np.column_stack([np.ones(n), np.minimum(T - tc, 0), np.maximum(T - tc, 0)])
        b, *_ = np.linalg.lstsq(X, y, rcond=None)
        sse = ((y - X @ b) ** 2).sum()
        if sse < best[0]:
            best = (sse, tc, b)
    if best[1] is None:
        return [np.nan] * 5
    sse2, tc, b = best
    bic1 = n * np.log(sse1 / n) + 2 * np.log(n)
    bic2 = n * np.log(sse2 / n) + 4 * np.log(n)
    return tc, b[1], b[2], 1 - sse2 / sst, bic2 - bic1


def main():
    rep = Report("23_temperature_threshold", "23. 기온과 수질: TN 임계기온, TP 수온 가설",
                 "건기일만으로 기온과 TN·TP의 관계를 보고, 처리장별로 TN이 오르기 시작하는 기온을 구한다.")
    if not C.WEATHER_PKL.exists():
        rep.p("⏳ 자료 대기: 먼저 21_merge_weather.py 를 실행하세요(기상자료 필요).")
        rep.save()
        return
    df = load_clean()
    df = df[df["sid"].isin(valid_sids(df, "TN"))]
    wx = pd.read_pickle(C.WEATHER_PKL)
    df = df.merge(wx, on=["site", "date"], how="left")
    dry = df[df["dry"] == True]  # noqa: E712
    rep.kv({"분석 방류구": dry["sid"].nunique(), "건기일 행수": len(dry)})

    rows = []
    curves = {}
    for sid, g in dry.groupby("sid"):
        r = {"sid": sid, "site": g["site"].iloc[0], "시군": g["sigun"].iloc[0], "Q중앙": g["Q"].median()}
        y = np.log(g["TN"].where(g["TN"] > 0)).values
        best_k, best_rho = None, 0
        for k in (7, 14, 30):
            rho = pd.Series(y).corr(g[f"ta_ma{k}"].reset_index(drop=True), method="spearman")
            r[f"TN_rho_ma{k}"] = rho
            if np.isfinite(rho) and abs(rho) > abs(best_rho):
                best_k, best_rho = k, rho
        r["TN_최적창일"] = best_k
        if best_k:
            T = g[f"ta_ma{best_k}"].values
            tc, bl, bh, r2, dbic = seg_fit(T, y)
            r.update({"TN_임계기온": tc, "TN_임계이하_기울기pct/℃": (np.exp(bl) - 1) * 100 if np.isfinite(bl) else np.nan,
                      "TN_임계이상_기울기pct/℃": (np.exp(bh) - 1) * 100 if np.isfinite(bh) else np.nan,
                      "TN_꺾인선R2": r2, "TN_ΔBIC": dbic})
            if len(curves) < 9 and np.isfinite(tc):
                curves[sid] = (T, y, tc)
            r["TN_임계이하_일수_연평균"] = (T < tc).sum() / max(1, g["date"].dt.year.nunique()) if np.isfinite(tc) else np.nan
        # TP 수온 가설
        yp = np.log(g["TP"].where(g["TP"] > 0))
        T30 = g["ta_ma14"]
        ok = yp.notna() & T30.notna() & g["Q"].notna()
        if ok.sum() > 100:
            sl = stats.linregress(T30[ok], yp[ok])
            r["TP_기온기울기pct/℃"] = (np.exp(sl.slope) - 1) * 100
            r["TP_기온_p"] = sl.pvalue
            # 유량 통제 편상관
            lq = np.log(g.loc[ok, "Q"])
            rt = stats.linregress(lq, T30[ok]).intercept + stats.linregress(lq, T30[ok]).slope * lq
            rp = stats.linregress(lq, yp[ok]).intercept + stats.linregress(lq, yp[ok]).slope * lq
            r["TP_기온_편상관(유량통제)"] = np.corrcoef(T30[ok] - rt, yp[ok] - rp)[0, 1]
        rows.append(r)
    t = pd.DataFrame(rows)
    if C.SITE_FACILITY_CSV.exists():
        fac = pd.read_csv(C.SITE_FACILITY_CSV, encoding="utf-8-sig")
        if "process" in fac:
            t["공법"] = t["site"].map(fac.drop_duplicates("site").set_index("site")["process"])
    rep.csv(t, "temperature_by_sid.csv")

    rep.h("1. TN과 기온")
    good = t[t["TN_ΔBIC"] < -10]
    rep.kv({"꺾인선이 직선보다 확실히 나은(ΔBIC<-10) 방류구": len(good),
            "임계기온 중앙값(℃)": good["TN_임계기온"].median(),
            "임계 이하 기울기 중앙(%/℃)": good["TN_임계이하_기울기pct/℃"].median(),
            "가장 잘 맞는 기온 창(최빈, 일)": t["TN_최적창일"].mode().iloc[0] if t["TN_최적창일"].notna().any() else np.nan})
    rep.p("임계 이하 기울기가 음수일수록(예: -5%/℃) 기온이 1℃ 내려갈 때 TN이 그만큼 오른다는 뜻.")
    rep.table(good.sort_values("TN_임계이하_기울기pct/℃")[["sid", "시군", "Q중앙", "TN_임계기온", "TN_임계이하_기울기pct/℃",
                                                        "TN_임계이상_기울기pct/℃", "TN_꺾인선R2", "TN_최적창일"]].head(30),
              "저온 취약 상위 30(기울기가 가파른 순)", digits=2)
    if "공법" in t and t["공법"].notna().any():
        rep.table(good.groupby("공법")[["TN_임계기온", "TN_임계이하_기울기pct/℃"]].median().reset_index(), "공법별 중앙값", digits=2)
        groups = [gg["TN_임계이하_기울기pct/℃"].dropna() for _, gg in good.groupby("공법") if gg["TN_임계이하_기울기pct/℃"].notna().sum() >= 5]
        if len(groups) >= 2:
            rep.kv({"공법 간 기울기 차이 Kruskal p": stats.kruskal(*groups).pvalue})

    rep.h("2. TP와 기온(여름 상승의 수온 가설)")
    if "TP_기온기울기pct/℃" in t:
        rep.kv({"TP 기온 기울기 중앙(%/℃)": t["TP_기온기울기pct/℃"].median(),
                "기온↑ TP↑ 유의(p<0.01) 방류구": int(((t["TP_기온기울기pct/℃"] > 0) & (t["TP_기온_p"] < 0.01)).sum()),
                "유량 통제 편상관 중앙": t["TP_기온_편상관(유량통제)"].median()})
        rep.table(t.sort_values("TP_기온기울기pct/℃", ascending=False)[["sid", "시군", "TP_기온기울기pct/℃", "TP_기온_p", "TP_기온_편상관(유량통제)"]].head(20),
                  "기온이 오를수록 TP가 오르는 방류구 상위 20", digits=3)

    if curves:
        fig, axes = plt.subplots(3, 3, figsize=(13, 10))
        for ax, (sid, (T, y, tc)) in zip(axes.ravel(), curves.items()):
            ax.scatter(T, np.exp(y), s=3, alpha=0.3)
            ax.axvline(tc, color="red", lw=1)
            ax.set_title(f"{sid}  Tc={tc:.1f}℃", fontsize=9)
            ax.set_xlabel("이동평균 기온(℃)")
            ax.set_ylabel("TN(mg/L)")
        rep.fig(fig, "tn_temperature_examples.png", "빨간 선 = 추정 임계기온")
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.hist(good["TN_임계기온"].dropna(), bins=20)
    ax.set_xlabel("TN 임계기온(℃)")
    ax.set_ylabel("방류구 수")
    rep.fig(fig, "tn_threshold_hist.png")
    rep.save()


if __name__ == "__main__":
    main()
