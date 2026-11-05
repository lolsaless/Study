# -*- coding: utf-8 -*-
"""
24. TMS × 국가수질자동측정망(하천) 연계 예비분석  — 기상자료 없이 가능한 부분

질문
 Q1. 비가 와도 최종 방류구 TMS는 반응하지 않는가?  (사용자 가설: 반응 안 함 — 처리용량 초과분은 우회·월류)
     → 강우일을 TMS가 아니라 '하천'(탁도 급등·전기전도도 희석)으로 독립 정의한 뒤,
       그날 TMS 방류 유량·농도가 평소(건기)와 다른지 방류구별로 검정한다.
 Q2. 같은 날 하천은 얼마나 변하나? (TMS에 안 보이는 부하가 하천에는 보이는지)
 Q3. 하천 수질에 하수처리장의 '요일 지문'이 남아 있나?
     → 하천 일자료의 건기 요일 패턴과 상류 TMS 부하의 요일 패턴을 비교(시차 0~3일).

입력
  work/tms_clean.pkl (01번), data/tms_location_geocoded.csv(선택)
  ../../물환경정보시스템_국가수질자동측정망/Raw data/Data/한강_일별.csv
주의
  하천 측정소-상류 처리장 연결(UPSTREAM)은 행정구역 기반 '가설'이다. 중권역·표준유역 경계와
  측정소 좌표로 반드시 확인한 뒤 써야 한다. 하천 유량이 없으므로 부하 수지(기여율)는 계산하지 않는다.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats

import config as C
from common import Report, load_clean, valid_sids, fdr

def _find_river_csv():
    """config.RIVER_DAILY_CSV 가 없으면 이 폴더의 상위 1~3단계에서 '물환경정보시스템_국가수질자동측정망/Raw data/Data/한강_일별.csv' 를 찾는다."""
    if getattr(C, "RIVER_DAILY_CSV", None):
        return Path(C.RIVER_DAILY_CSV)
    rel = Path("물환경정보시스템_국가수질자동측정망") / "Raw data" / "Data" / "한강_일별.csv"
    for up in [C.BASE_DIR.parent, C.BASE_DIR.parent.parent, C.BASE_DIR.parent.parent.parent]:
        if (up / rel).exists():
            return up / rel
    return C.BASE_DIR.parent.parent / rel


RIVER_CSV = _find_river_csv()
MIN_HOURS = 18          # 하천 일평균을 쓸 최소 유효 시간수
TURB_RATIO = 3.0        # 탁도 일평균 ÷ 31일 이동중앙값 ≥ 3  → 유출 사건
EC_RATIO = 0.80         # 전기전도도 일평균 ÷ 31일 이동중앙값 ≤ 0.8 → 빗물 희석
REGIONAL_SHARE = 0.25   # 경기권 측정소 중 사건 측정소 비율 ≥ 25% → 광역 강우일
GG_STATIONS = ["가평", "경안천", "구리", "복하천", "청미천", "신천", "포천", "한탄강",
               "양평", "여주", "능서", "흥천", "미산", "강천"]

# 측정소 → 상류 TMS 사업장(행정구역 기반 가설; 확인 필요)
UPSTREAM = {
    "경안천": {"용인하수", "용인동부하수", "용인모현하수", "에버랜드(용인)", "용인정수(용인)", "광주경안하수",
              "광주오포하수", "광주양벌하수", "광주하수", "광주곤지암하수", "광주도척하수", "광주삼리하수",
              "롯데칠성음료(광주)"},
    "복하천": {"이천하수", "이천부필하수", "이천단월하수", "이천마장하수", "오비맥주(이천)", "하이트진로(이천)",
              "신세계푸드(이천)", "사조씨피케이(이천)", "팔도(이천)", "에스케이하이이엔지(이천)",
              "샘표식품(이천)", "동원시스템즈(이천)"},
    "청미천": {"안성일죽하수", "안성죽산하수", "도드람LPC(안성)", "용인백암하수", "이천장호원하수",
              "이천율면하수", "이천송계하수"},
    "신천": {"양주신천하수", "동두천하수", "양주남방하수", "양주옥정하수", "서울우유(양주)", "양주홍죽폐수",
            "양주기산하수", "동진섬유(양주)"},
    "포천": {"포천하수", "포천소흘하수", "포천용정폐수", "포천장자폐수", "신평패션칼라사업협동조합(포천)",
            "대원제지(포천)"},
}


def ratio_to_base(s, win=31):
    base = s.rolling(win, center=True, min_periods=10).median()
    return s / base


def load_river():
    rv = pd.read_csv(RIVER_CSV, encoding="utf-8-sig", parse_dates=["날짜"])
    rv = rv.rename(columns={"날짜": "date", "측정소": "st"})
    for v in ["Turb", "EC", "TOC", "TN", "TP", "WT"]:
        if f"{v}_mean" in rv:
            rv[v] = rv[f"{v}_mean"].where(rv[f"{v}_n"] >= MIN_HOURS)
    return rv[["st", "date", "Turb", "EC", "TOC", "TN", "TP", "WT"]]


def river_events(rv):
    flags = []
    for st, g in rv.groupby("st"):
        g = g.set_index("date").sort_index().asfreq("D")
        f = pd.DataFrame(index=g.index)
        f["turb"] = ratio_to_base(g["Turb"]) >= TURB_RATIO
        f["ec"] = ratio_to_base(g["EC"]) <= EC_RATIO
        f["ok"] = g["Turb"].notna() | g["EC"].notna()
        f["ev"] = f["turb"] | f["ec"]
        f["st"] = st
        flags.append(f.reset_index())
    fl = pd.concat(flags)
    gg = fl[fl["st"].isin(GG_STATIONS) & fl["ok"]]
    reg = gg.groupby("date").agg(share=("ev", "mean"), n=("ev", "size"))
    reg["event"] = (reg["share"] >= REGIONAL_SHARE) & (reg["n"] >= 6)
    return fl, reg


def day_classes(event_series):
    """사건일(0일·+1일)과 건기 기준일(앞뒤 3일 안에 사건 없음)"""
    ev = event_series.astype(bool)
    wet = ev | ev.shift(1, fill_value=False)
    near = ev.copy()
    for k in range(1, 4):
        near |= ev.shift(k, fill_value=False) | ev.shift(-k, fill_value=False)
    dry = ~near
    return wet, dry


def main():
    rep = Report("24_river_link_pilot", "24. TMS × 하천 자동측정망 연계 예비분석",
                 "하천 자료로 강우일을 독립적으로 정의해 TMS 방류수의 강우 반응을 검정하고(사용자 가설), "
                 "하천 수질에 하수처리장 신호(요일 지문)가 남는지 확인한다.")
    if not RIVER_CSV.exists():
        rep.p(f"⏳ 하천 자료 없음: `{RIVER_CSV}`")
        rep.save()
        return

    rv = load_river()
    fl, reg = river_events(rv)
    reg.to_csv(rep.dir / "regional_river_events.csv", encoding="utf-8-sig")
    period = (rv["date"].min(), rv["date"].max())

    rep.h("1. 하천 자료로 정의한 광역 강우(유출) 사건일")
    rep.p(f"측정소별로 탁도 일평균이 31일 이동중앙값의 {TURB_RATIO}배 이상이거나 전기전도도가 {EC_RATIO}배 이하이면 사건, "
          f"경기권 {len(GG_STATIONS)}개 측정소 중 {REGIONAL_SHARE:.0%} 이상이 사건이면 '광역 강우일'로 본다. "
          "TMS 자료를 쓰지 않으므로 TMS 반응을 검정하는 데 순환논리가 없다.")
    ev_days = reg.index[reg["event"]]
    rep.kv({"하천 자료 기간": f"{period[0]:%Y-%m-%d} ~ {period[1]:%Y-%m-%d}",
            "광역 강우일 수": len(ev_days),
            "그중 6~9월(%)": (ev_days.month.isin([6, 7, 8, 9]).mean() * 100) if len(ev_days) else np.nan})
    top = reg[reg["event"]].sort_values("share", ascending=False).head(25).reset_index()
    rep.table(top, "사건 측정소 비율 상위 광역 강우일")

    # 기상청 강수(21번 산출물)와 일치도
    if C.WEATHER_PKL.exists():
        wx = pd.read_pickle(C.WEATHER_PKL)
        rain = wx.groupby("date")["rain_mm"].mean()
        rain2 = rain.rolling(2, min_periods=1).sum()          # 당일+전일(유출 지연)
        j = reg.join(rain2.rename("rain_2d"), how="inner")
        if len(j):
            big = j["rain_2d"] >= 20
            rep.kv({"검증: 하천 사건일의 도평균 2일 강수 중앙(mm)": j.loc[j["event"], "rain_2d"].median(),
                    "검증: 비사건일의 도평균 2일 강수 중앙(mm)": j.loc[~j["event"], "rain_2d"].median(),
                    "검증: 2일 강수 ≥20mm 날 중 하천 사건일 비율(%)": j.loc[big, "event"].mean() * 100,
                    "검증: 하천 사건일 중 2일 강수 <5mm 비율(%)": (j.loc[j["event"], "rain_2d"] < 5).mean() * 100})
    # TMS 고유량일(04번)과 일치도
    f04 = C.RESULTS_DIR / "04_flow_analysis" / "regional_flow_signal_by_date.csv"
    if f04.exists():
        t04 = pd.read_csv(f04, parse_dates=["date"]).set_index("date")
        j = reg.join(t04, how="inner")
        if "고유량방류구비율" in j:
            rho = stats.spearmanr(j["share"], j["고유량방류구비율"], nan_policy="omit")
            hi = j["고유량방류구비율"] >= j["고유량방류구비율"].quantile(0.95)
            rep.kv({"하천 사건비율 vs TMS 고유량 방류구 비율 Spearman ρ": rho[0],
                    "TMS 상위 5% 고유량일 중 하천 사건일 비율(%)": j.loc[hi, "event"].mean() * 100,
                    "하천 사건일 중 TMS 상위 5% 고유량일 비율(%)": hi[j["event"]].mean() * 100})

    # ── Q1. TMS 방류수 반응 ──
    rep.h("2. Q1 — 광역 강우일에 TMS 방류수는 변하는가")
    df = load_clean()
    df = df[df["sid"].isin(valid_sids(df, "TN"))]
    df = df[(df["date"] >= period[0]) & (df["date"] <= period[1])]
    ev = reg["event"].reindex(pd.date_range(*period, freq="D"), fill_value=False)
    wet, dry = day_classes(ev)
    rows = []
    for sid, g in df.groupby("sid"):
        g = g.set_index("date").sort_index()
        g = g[~g.index.duplicated()].asfreq("D")
        r = {"sid": sid, "site": g["site"].dropna().iloc[0], "시군": g["sigun"].dropna().iloc[0] if g["sigun"].notna().any() else "",
             "Q중앙": g["Q"].median()}
        for v in ["Q", "TOC", "SS", "TN", "TP"]:
            x = g[v].where(g[v] > 0)
            base = x.where(dry.reindex(x.index, fill_value=False)).rolling(31, center=True, min_periods=8).median()
            base = base.interpolate(limit_direction="both")
            rr = np.log(x / base)
            a = rr[wet.reindex(rr.index, fill_value=False)].dropna()
            b = rr[dry.reindex(rr.index, fill_value=False)].dropna()
            if len(a) >= 8 and len(b) >= 60:
                r[f"{v}_비"] = float(np.exp(a.median() - b.median()))
                r[f"{v}_p"] = stats.mannwhitneyu(a, b).pvalue
            else:
                r[f"{v}_비"], r[f"{v}_p"] = np.nan, np.nan
        rows.append(r)
    res = pd.DataFrame(rows)
    for v in ["Q", "TOC", "SS", "TN", "TP"]:
        res[f"{v}_q"] = fdr(res[f"{v}_p"].values)

    summ = []
    for v in ["Q", "TOC", "SS", "TN", "TP"]:
        ok = res[f"{v}_비"].notna()
        sig = ok & (res[f"{v}_q"] < 0.05)
        summ.append({"항목": v, "방류구수": int(ok.sum()),
                     "강우일/건기 비 중앙": res.loc[ok, f"{v}_비"].median(),
                     "비 p10": res.loc[ok, f"{v}_비"].quantile(0.1), "비 p90": res.loc[ok, f"{v}_비"].quantile(0.9),
                     "유의 증가(%)": (sig & (res[f"{v}_비"] > 1)).sum() / ok.sum() * 100,
                     "유의 감소(%)": (sig & (res[f"{v}_비"] < 1)).sum() / ok.sum() * 100,
                     "±10% 이상 변화(%)": ((res.loc[ok, f"{v}_비"] - 1).abs() >= 0.10).mean() * 100})
    summ = pd.DataFrame(summ)
    rep.table(summ, "광역 강우일(0·+1일) vs 건기일 — 방류구별 중앙값 비의 분포 (FDR q<0.05)")
    rep.p("읽는 법: 비=1.10 이면 강우일 값이 건기보다 10% 높다. Q는 TMS 배출량÷농도로 역산한 처리수 유량이다.")
    rep.csv(res.sort_values("Q_비", ascending=False), "tms_wet_vs_dry_by_sid.csv")
    rep.table(res.sort_values("Q_비", ascending=False)[["sid", "시군", "Q중앙", "Q_비", "TOC_비", "SS_비", "TN_비", "TP_비"]].head(15),
              "강우일 유량 증가가 큰 방류구 상위 15")
    rep.table(res.sort_values("Q_비")[["sid", "시군", "Q중앙", "Q_비", "TOC_비", "SS_비", "TN_비", "TP_비"]].head(10),
              "강우일에도 유량이 거의 늘지 않는 방류구(용량 천장·분류식 후보) 10")

    # ── Q2. 하천 반응 ──
    rep.h("3. Q2 — 같은 날 하천은 얼마나 변하나")
    rrows = []
    for st, g in rv.groupby("st"):
        if st not in GG_STATIONS:
            continue
        g = g.set_index("date").sort_index().asfreq("D")
        r = {"측정소": st}
        for v in ["Turb", "EC", "TOC", "TN", "TP"]:
            x = g[v].where(g[v] > 0)
            base = x.where(dry.reindex(x.index, fill_value=False)).rolling(31, center=True, min_periods=8).median()
            base = base.interpolate(limit_direction="both")
            rr = np.log(x / base)
            a = rr[wet.reindex(rr.index, fill_value=False)].dropna()
            b = rr[dry.reindex(rr.index, fill_value=False)].dropna()
            r[f"{v}_비"] = float(np.exp(a.median() - b.median())) if len(a) >= 8 and len(b) >= 60 else np.nan
        rrows.append(r)
    rres = pd.DataFrame(rrows)
    rep.table(rres, "경기권 하천 측정소: 광역 강우일 vs 건기 중앙값 비")
    tms_med = summ.set_index("항목")["강우일/건기 비 중앙"]
    rep.kv({"TMS 방류수 TOC 비(중앙)": tms_med.get("TOC"), "하천 TOC 비(측정소 중앙)": rres["TOC_비"].median(),
            "TMS 방류수 TP 비(중앙)": tms_med.get("TP"), "하천 TP 비(측정소 중앙)": rres["TP_비"].median()})

    # ── Q3. 요일 지문 ──
    rep.h("4. Q3 — 하천 수질에 하수처리장의 요일 지문이 남는가(건기일)")
    rep.p("건기일만 써서 31일 이동중앙값 대비 로그 편차의 요일 평균을 구한다. 하천 쪽은 Kruskal-Wallis로 요일 차이를 검정하고, "
          "상류 처리장(가설 연결) 합산 부하의 요일 패턴과 0~3일 시차로 상관을 본다. 요일 지문이 강하면 점오염원 기여가 크다는 간접 증거다.")
    dow_rows, prof = [], {}
    all_types = load_clean(types=None)
    all_types = all_types[(all_types["date"] >= period[0]) & (all_types["date"] <= period[1])]
    for st, sites in UPSTREAM.items():
        g = rv[rv["st"] == st].set_index("date").sort_index().asfreq("D")
        up = all_types[all_types["site"].isin(sites)]
        n_up = up["site"].nunique()
        for v in ["TOC", "TN", "TP"]:
            x = g[v].where(g[v] > 0)
            if x.notna().sum() < 200:
                continue
            an = np.log(x / x.rolling(31, center=True, min_periods=10).median())
            an = an[dry.reindex(an.index, fill_value=False)].dropna()
            grp = [an[an.index.day_of_week == d] for d in range(7)]
            if min(len(q) for q in grp) < 10:
                continue
            kw = stats.kruskal(*grp).pvalue
            rprof = np.array([q.mean() for q in grp])
            lv = f"{v}_load"
            L = up.groupby("date")[lv].sum(min_count=1).asfreq("D")
            L = L.where(up.groupby("date")[lv].count().asfreq("D") >= max(1, 0.8 * n_up))
            la = np.log(L / L.rolling(31, center=True, min_periods=10).median())
            best = (np.nan, np.nan)
            if la.notna().sum() > 200:
                la_d = la[dry.reindex(la.index, fill_value=False)].dropna()
                tprof = np.array([la_d[la_d.index.day_of_week == d].mean() for d in range(7)])
                for lag in range(4):
                    rr = np.corrcoef(rprof, np.roll(tprof, lag))[0, 1]
                    if np.isnan(best[0]) or rr > best[0]:
                        best = (rr, lag)
                prof[(st, v)] = (rprof, tprof)
            dow_rows.append({"측정소": st, "항목": v, "상류 사업장수": n_up, "하천 요일차 KW p": kw,
                             "하천 요일진폭(%)": (np.exp(rprof.max() - rprof.min()) - 1) * 100,
                             "하천 최저 요일": "월화수목금토일"[int(np.argmin(rprof))],
                             "TMS부하-하천 요일패턴 r(최대)": best[0], "시차(일)": best[1]})
    dres = pd.DataFrame(dow_rows)
    if len(dres):
        dres["KW q"] = fdr(dres["하천 요일차 KW p"].values)
    rep.table(dres, "측정소·항목별 요일 지문")
    rep.csv(dres, "river_weekday_fingerprint.csv")

    if prof:
        n = len(prof)
        ncol = min(4, n)
        nrow = int(np.ceil(n / ncol))
        fig, axes = plt.subplots(nrow, ncol, figsize=(3.2 * ncol, 2.8 * nrow), sharey=False, squeeze=False)
        for ax in axes.flat[n:]:
            ax.set_visible(False)
        axes = axes.flat
        for ax, ((st, v), (rp, tp)) in zip(axes, prof.items()):
            ax.plot(range(7), (np.exp(rp) - 1) * 100, "o-", label="하천")
            ax.plot(range(7), (np.exp(tp) - 1) * 100, "s--", label="상류 TMS 부하")
            ax.set_xticks(range(7), list("월화수목금토일"))
            ax.axhline(0, color="grey", lw=0.5)
            ax.set_title(f"{st} {v}")
        axes[0].set_ylabel("건기 편차(%)")
        axes[0].legend(fontsize=7)
        rep.fig(fig, "weekday_fingerprint.png", "하천 vs 상류 TMS 부하 요일 패턴(건기)")

    # 그림: 사건일 TMS vs 하천
    fig, ax = plt.subplots(figsize=(6, 3.5))
    data = [res["Q_비"].dropna(), res["TOC_비"].dropna(), res["TP_비"].dropna(),
            rres["TOC_비"].dropna(), rres["TP_비"].dropna(), rres["Turb_비"].dropna()]
    ax.boxplot(data, showfliers=False)  # labels= 인자는 matplotlib 버전마다 이름이 달라 따로 붙인다
    ax.set_xticks(range(1, 7))
    ax.set_xticklabels(["TMS Q", "TMS TOC", "TMS TP", "하천 TOC", "하천 TP", "하천 탁도"])
    ax.axhline(1, color="grey", lw=0.6)
    ax.set_yscale("log")
    ax.set_ylabel("광역 강우일 / 건기 (중앙값 비)")
    rep.fig(fig, "wet_dry_tms_vs_river.png", "같은 강우일에 방류수와 하천의 반응 크기 비교")

    rep.h("5. 해석 주의")
    rep.p("- 강우일은 하천 탁도·전기전도도로 정의했다. 국지성 소나기는 놓치고, 해빙·공사 탁도는 섞일 수 있다. 기상청 강수(21번)로 교차검증해야 한다.\n"
          "- TMS 유량은 '방류구로 나간 처리수'다. 우회·월류(바이패스)량은 보이지 않으므로, 유량 증가가 작다는 것이 유입 증가가 작다는 뜻은 아니다.\n"
          "- 측정소-처리장 연결(UPSTREAM)은 행정구역 기반 가설이다. 측정소 좌표·표준유역으로 확정해야 한다.\n"
          "- 하천 유량이 없어 하천 부하와 TMS 부하의 수지(점오염 기여율, 강우시 미계측 부하)는 아직 계산할 수 없다.")
    rep.save()


if __name__ == "__main__":
    main()
