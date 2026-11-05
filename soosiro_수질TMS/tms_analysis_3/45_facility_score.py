# -*- coding: utf-8 -*-
"""
45. 처리시설 관리 평가(연구 방향 3) — 영역별 점수(기준 여유·안정성·강우 대응·자료 관리), 규모 보정·연도 안정성, 약점 진단, 원인 분석, 재정지원 우선순위(필요도×하천영향×개선여지)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats

import config as C
from core import Report, io

REQUIRES = ["tms"]
LEVEL = "연계"
PARAMS = ["TOC", "SS", "TN", "TP"]


def flat_share(s, run=7):
    x = s.dropna()
    if len(x) < run:
        return np.nan
    grp = (x != x.shift()).cumsum()
    return float((x.groupby(grp).transform("size") >= run).mean())


def metrics(g, std, rain_days):
    """방류구 1곳의 지표(값이 클수록 나쁨)"""
    r = {}
    for p in PARAMS:
        r[f"{p}_r"] = g[p].quantile(0.95) / std[p] if g[p].notna().sum() > 100 else np.nan
    ratio = [r[f"{p}_r"] for p in PARAMS if pd.notna(r[f"{p}_r"])]
    r["p95/기준 최대"] = max(ratio) if ratio else np.nan
    r["빠듯한 항목"] = PARAMS[int(np.nanargmax([g[p].quantile(0.95) / std[p] if g[p].notna().sum() > 100 else -1 for p in PARAMS]))]
    over = pd.concat([g[p] > std[p] for p in PARAMS if p in g], axis=1).any(axis=1)
    r["초과일%"] = float(over[g[PARAMS].notna().any(axis=1)].mean() * 100)
    for p in ["TN", "TP"]:
        x = g[p].dropna()
        r[f"{p} 변동(MAD/중앙)"] = float((x - x.median()).abs().median() / x.median()) if len(x) > 100 and x.median() > 0 else np.nan
    m = g.assign(mm=g["date"].dt.month)
    w, s = m.loc[m["mm"].isin([12, 1, 2]), "TN"].median(), m.loc[m["mm"].isin([6, 7, 8]), "TN"].median()
    r["TN 겨울/여름"] = w / s if s and s > 0 else np.nan
    q = g.set_index("date")["Q"].asfreq("D")
    if rain_days is not None and q.notna().sum() > 200:
        base = q.rolling(31, center=True, min_periods=10).median()
        rr = (q / base)[q.index.isin(rain_days)]
        r["강우일 유량 배율"] = float(rr.median()) if rr.notna().sum() >= 5 else np.nan
    cal = (g["date"].max() - g["date"].min()).days + 1
    r["결측%"] = float((1 - g["TN"].notna().sum() / cal) * 100)
    r["고정값%"] = float(np.nanmean([flat_share(g[p]) for p in ["pH", "SS", "TN"] if p in g]) * 100)
    r["유량 중앙(m3/일)"] = float(g["Q"].median())
    tl = g.set_index("date")["TOC_load"].dropna()
    if len(tl) > 200:
        dow = (np.log(tl.clip(lower=1e-3)) - np.log(tl.clip(lower=1e-3)).rolling(29, center=True, min_periods=10).median()).groupby(tl.index.dayofweek).mean()
        r["요일 진폭%(산업폐수 지표)"] = float((np.exp(dow.max() - dow.min()) - 1) * 100)
    return r


DOMAINS = {"기준 여유": ["p95/기준 최대", "초과일%"], "안정성": ["TN 변동(MAD/중앙)", "TP 변동(MAD/중앙)", "TN 겨울/여름"],
           "강우 대응": ["강우일 유량 배율"], "자료 관리": ["결측%", "고정값%"]}


def score(t):
    """영역 점수 0~100(100 = 가장 잘 관리). 지표 백분위의 반대값 평균"""
    out = pd.DataFrame(index=t.index)
    for dom, cols in DOMAINS.items():
        cols = [c for c in cols if c in t and t[c].notna().sum() > 10]
        out[dom] = (1 - t[cols].rank(pct=True)).mean(axis=1) * 100 if cols else np.nan
    wts = {k: v for k, v in C.FACILITY_SCORE_WEIGHTS.items() if out[k].notna().any()}
    tot = sum(wts.values())
    out["종합점수"] = sum(out[k].fillna(out[k].median()) * v / tot for k, v in wts.items())
    return out


def main():
    rep = Report("45_facility_score", "45. 처리시설 관리 평가와 재정지원 우선순위", level=LEVEL,
                 purpose="방류 TMS 로 공공하수처리시설의 관리 수준을 4개 영역 점수로 매기고, 점수가 낮은 이유(약점·조건)를 진단한 뒤, "
                         "'점수가 낮을수록 지원'의 역효과를 피하도록 필요도 × 하천 영향 × 개선 여지로 우선순위를 만든다. RESEARCH_REVIEW.md 방향 3.")
    tms = io.load_tms()
    if tms is None:
        return rep.wait("방류 TMS 정제자료가 없다.", ["tms_analysis_2 01_preprocess.py"])
    tms = tms[tms["site_type"].isin(C.FACILITY_TYPES)].copy()
    tms["date"] = pd.to_datetime(tms["date"])
    region = {}
    if C.TMS_SITE_REGION.exists():
        rr = pd.read_csv(C.TMS_SITE_REGION, encoding="utf-8-sig")
        region = rr.dropna(subset=["region"]).set_index("site")["region"].astype(str).str.upper().str.replace("Ⅰ", "I").to_dict()
    n_reg = sum(s in region for s in tms["site"].unique())
    rep.p(f"방류수 기준 지역: {n_reg}/{tms['site'].nunique()}곳 입력됨, 나머지는 {C.DEFAULT_REGION}지역(가장 엄격) 가정. "
          "⚠ TP 기준이 지역에 따라 0.2~2.0 mg/L 로 달라 '기준 여유' 점수가 크게 바뀔 수 있다 → site_region.csv 입력 후 다시 실행.")
    ev = C.WORK_DIR / "regional_event_days.csv"
    rain_days = None
    if ev.exists():
        e = pd.read_csv(ev, encoding="utf-8-sig", parse_dates=["date"])
        rain_days = pd.DatetimeIndex(e.loc[e["basin"] == "한강", "date"])
        rep.p(f"강우일: 30번이 하천 자료로 정의한 한강권 광역 사건일 {len(rain_days)}일(경기도 처리장에 적용).")

    rows, yrows = [], []
    for sid, g in tms.groupby("sid"):
        if g["TN"].notna().sum() < 300:
            continue
        reg = region.get(g["site"].iloc[0], C.DEFAULT_REGION)
        std = C.DISCHARGE_STANDARDS.get(reg, C.DISCHARGE_STANDARDS[C.DEFAULT_REGION])
        rows.append({"sid": sid, "site": g["site"].iloc[0], "sigun": g["sigun"].iloc[0], "지역": reg, **metrics(g, std, rain_days)})
        for y, gy in g.groupby(g["date"].dt.year):
            if gy["TN"].notna().sum() >= 150:
                yrows.append({"sid": sid, "year": y, **metrics(gy, std, rain_days)})
    t = pd.DataFrame(rows).set_index("sid")
    S = score(t)
    t = t.join(S)
    # 규모 보정: 각 영역 점수에서 처리 규모(log 유량) 영향을 회귀로 빼고 다시 백분위화
    lq = np.log(t["유량 중앙(m3/일)"].clip(lower=1))
    X = np.column_stack([np.ones(len(t)), lq, lq ** 2])
    adj = pd.DataFrame(index=t.index)
    for dom in DOMAINS:
        y = t[dom].fillna(t[dom].median()).values
        res = y - X @ np.linalg.lstsq(X, y, rcond=None)[0]
        adj[dom] = pd.Series(res, index=t.index).rank(pct=True) * 100
    t["규모보정점수"] = sum(adj[k] * v for k, v in C.FACILITY_SCORE_WEIGHTS.items()) / sum(C.FACILITY_SCORE_WEIGHTS.values())
    t["등급"] = pd.qcut(t["종합점수"].rank(method="first"), 5, labels=["E", "D", "C", "B", "A"])
    t["약점 영역"] = t[list(DOMAINS)].idxmin(axis=1)

    yt = pd.DataFrame(yrows)
    stab = np.nan
    if yt["year"].nunique() >= 2:
        ys = {y: score(g.set_index("sid"))["종합점수"] for y, g in yt.groupby("year")}
        yrs = sorted(ys)
        a, b = ys[yrs[-2]], ys[yrs[-1]]
        both = a.index.intersection(b.index)
        stab = stats.spearmanr(a[both], b[both])[0]
        t[f"점수_{yrs[-2]}"], t[f"점수_{yrs[-1]}"] = a, b
        t["개선폭"] = b - a
        low_both = ((a.rank(pct=True) <= 0.2) & (b.rank(pct=True) <= 0.2))
        t["두 해 연속 하위20%"] = low_both.reindex(t.index).fillna(False)
    rep.csv(t.reset_index(), "facility_scores.csv")

    rep.h("1. 점수 체계와 신뢰성")
    rep.table(pd.DataFrame([{"영역": k, "가중치": v, "지표(클수록 나쁨)": ", ".join(DOMAINS[k])} for k, v in C.FACILITY_SCORE_WEIGHTS.items()]))
    rho_size = stats.spearmanr(t["종합점수"], t["규모보정점수"])[0]
    rep.kv({"평가 방류구": len(t), "연도 간 점수 순위상관(ρ)": stab, "원점수-규모보정 순위상관(ρ)": rho_size,
            "규모와 점수 상관(ρ)": stats.spearmanr(lq, t["종합점수"])[0]})
    rep.finding(f"하수 방류구 {len(t)}곳 평가: 연도 간 점수 순위상관 ρ={stab:.2f}" + (" (보통 — 한 해 점수로 지원 대상을 정하지 말고 2년 이상 평균)" if stab < 0.7 else " (안정)")
                + f", 규모 보정 전후 ρ={rho_size:.2f}")
    # 기준 지역 민감도: 지역 입력이 없으면 TP 기준(0.2~2.0)이 점수를 좌우할 수 있다 → TP 를 뺀 '기준 여유'로 다시 계산
    if n_reg < tms["site"].nunique() * 0.8:
        alt = t.copy()
        alt["p95/기준 최대"] = [max([v for v in [r.get("TOC_r"), r.get("SS_r"), r.get("TN_r")] if pd.notna(v)] or [np.nan]) for _, r in alt.iterrows()]
        alt_s = score(alt.drop(columns=list(S.columns)))["종합점수"]
        lo_a, lo_b = set(t["종합점수"].nsmallest(20).index), set(alt_s.nsmallest(20).index)
        tp_tight = int((t.loc[list(lo_a), "빠듯한 항목"] == "TP").sum())
        rho_alt = stats.spearmanr(t["종합점수"], alt_s)[0]
        rep.kv({"하위 20곳 중 TP 가 가장 빠듯한 곳": tp_tight, "TP 제외 시 하위 20곳 유지": len(lo_a & lo_b), "TP 제외 점수와 순위상관": rho_alt})
        sig = t.loc[list(lo_a), "sigun"].value_counts().head(4)
        rep.finding(f"⚠ 기준 지역 미입력(I지역 가정): 하위 20곳 중 {tp_tight}곳이 TP 기준 때문, 주로 " + ", ".join(sig.index)
                    + f" — TP 기준을 빼면 하위 20곳 중 {len(lo_a & lo_b)}곳만 남는다. site_region.csv 입력 전 순위는 정책에 쓰지 말 것")

    rep.h("2. 관리 하위 시설과 약점")
    low = t.sort_values("종합점수").head(20)
    cols = ["site", "sigun", "종합점수", "규모보정점수", "약점 영역", "빠듯한 항목", "p95/기준 최대", "초과일%", "TN 겨울/여름", "강우일 유량 배율", "결측%"]
    cols += [c for c in ["두 해 연속 하위20%"] if c in t]
    rep.table(low.reset_index()[["sid"] + cols].round(2))
    wk = t[t["등급"] == "E"]["약점 영역"].value_counts()
    rep.finding("하위 20%(E등급) 시설의 주된 약점: " + ", ".join(f"{k} {v}곳" for k, v in wk.items()))
    if "두 해 연속 하위20%" in t:
        rep.finding(f"두 해 연속 하위 20%: {int(t['두 해 연속 하위20%'].sum())}곳 — 일시적 문제가 아닌 구조적 관리 취약 후보")

    rep.h("3. 점수가 낮은 이유(조건 변수와의 관계)")
    rep.p("순환논리를 피하려고, 설명 대상은 '수질 성과'(기준 여유·안정성 영역 평균)로 두고 조건 변수는 점수에 들어가지 않은 것만 쓴다"
          "(강우일 유량 배율은 강우 대응 영역이므로 수질 성과와만 비교).")
    t["수질 성과"] = t[["기준 여유", "안정성"]].mean(axis=1)
    cov = {"규모 log(유량)": lq, "요일 진폭%(산업폐수 지표)": t.get("요일 진폭%(산업폐수 지표)"),
           "강우일 유량 배율(I/I)": t.get("강우일 유량 배율")}
    fac = None
    if C.SITE_FACILITY_CSV.exists():
        fac = pd.read_csv(C.SITE_FACILITY_CSV, encoding="utf-8-sig").set_index("site")
        site = t["site"]
        if "capacity_m3d" in fac:
            cov["가동률(유량/용량)"] = t["유량 중앙(m3/일)"] / site.map(fac["capacity_m3d"])
        if "start_date" in fac:
            cov["가동 연수"] = (pd.Timestamp.now() - pd.to_datetime(site.map(fac["start_date"]), errors="coerce")).dt.days / 365
    rows = []
    for k, v in cov.items():
        if v is None:
            continue
        x = pd.concat([v, t["수질 성과"]], axis=1).dropna()
        if len(x) > 20:
            r, p = stats.spearmanr(x.iloc[:, 0], x.iloc[:, 1])
            rows.append({"조건 변수": k, "n": len(x), "수질 성과와 ρ": r, "p": p})
    ct = pd.DataFrame(rows)
    rep.table(ct.round(3))
    for _, r in ct[ct["p"] < 0.05].iterrows():
        rep.finding(f"수질 성과와 '{r['조건 변수']}' 상관 ρ={r['수질 성과와 ρ']:+.2f}(p={r['p']:.2g}) — "
                    + ("값이 클수록 성과 낮음" if r["수질 성과와 ρ"] < 0 else "값이 클수록 성과 높음"))
    if fac is None:
        rep.p("시설 제원(data/meta/site_facility.csv: site, capacity_m3d, process, start_date)이 없어 가동률·노후도·공법 분석은 생략했다(자료요구서 D-2).")
    sg = t.groupby("sigun")["종합점수"].agg(["size", "median"]).query("size >= 3").sort_values("median")
    rep.table(sg.head(10).round(1), "시군별 점수 중앙(3곳 이상, 하위 10)", index=True)

    rep.h("4. 재정지원 우선순위(필요도 × 하천 영향 × 개선 여지)")
    need = (100 - t["종합점수"]) / 100
    load = tms.groupby("sid")[["TN_load", "TP_load"]].mean()
    imp = (load["TN_load"].rank(pct=True) + load["TP_load"].rank(pct=True)).reindex(t.index) / 2
    es = C.WORK_DIR / "effluent_share.csv"
    if es.exists():                                    # 43번: 처리수 지배 하천으로 방류하는 시설은 영향 가중
        e = pd.read_csv(es, encoding="utf-8-sig")
        boost = {}
        for _, r in e.iterrows():
            for s_ in str(r["sites"]).split(";"):
                boost[s_] = max(boost.get(s_, 0), float(r["저유량 방류수 비율"]) if pd.notna(r["저유량 방류수 비율"]) else 0)
        imp = imp * (1 + t["site"].map(boost).fillna(0))
        rep.p("하천 영향 = 연평균 TN·TP 부하 백분위 × (1 + 저유량 방류수 비율[43번]). 처리수 지배 하천으로 방류하는 시설일수록 같은 개선의 하천 효과가 크다.")
    gap = (t["p95/기준 최대"] - t["p95/기준 최대"].median()).clip(lower=0)
    pot = gap.rank(pct=True).where(gap > 0, 0)
    t["우선순위지수"] = need.rank(pct=True) * imp.rank(pct=True) * (0.5 + 0.5 * pot)
    pr = t.sort_values("우선순위지수", ascending=False).head(20)
    rep.table(pr.reset_index()[["sid", "site", "sigun", "우선순위지수", "종합점수", "약점 영역", "빠듯한 항목"]].round(3))
    rep.finding("재정지원 우선순위 상위: " + ", ".join(pr["site"].head(5)) + " (필요도·하천 영향·개선 여지 곱)"
                + (" — ⚠ 방류수 기준 지역 입력 전 잠정 순위" if n_reg < tms["site"].nunique() * 0.8 else ""))
    if "개선폭" in t:
        rep.h("5. 개선 인센티브 후보(전년 대비 점수 상승)")
        up = t.sort_values("개선폭", ascending=False).head(10)
        rep.table(up.reset_index()[["sid", "site", "sigun", "개선폭", "종합점수"]].round(1))
        rep.p("정책 설계: ① 개선지원 트랙(4장 우선순위: 필요한 곳에 시설·운영 개선 예산) + ② 성과 인센티브 트랙(5장 개선폭: 나아진 곳에 보상). "
              "①만 있으면 '관리가 나쁠수록 지원'이라는 역효과가 생긴다. 환경부 공공하수도 운영관리 실태평가와 겹치지 않게 TMS 기반 객관 지표로 보완하는 형태가 현실적이다.")

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    axes[0].scatter(lq, t["종합점수"], s=10)
    axes[0].set_xlabel("log 방류 유량(m³/일)")
    axes[0].set_ylabel("종합점수")
    if "개선폭" in t:
        axes[1].scatter(t[f"점수_{yrs[-2]}"], t[f"점수_{yrs[-1]}"], s=10)
        axes[1].plot([0, 100], [0, 100], color="gray")
        axes[1].set_xlabel(f"{yrs[-2]} 점수")
        axes[1].set_ylabel(f"{yrs[-1]} 점수")
    fig.tight_layout()
    rep.fig(fig, "score_size_years.png", "규모와 점수, 연도 간 점수 일치")
    rep.save()


if __name__ == "__main__":
    main()
