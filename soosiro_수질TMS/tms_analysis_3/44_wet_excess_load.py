# -*- coding: utf-8 -*-
"""
44. 강우 초과 부하(연구 방향 2) — '희석만 됐을 때 예상 농도'보다 높은 만큼을 강우 유래 부하로 보고, 사건 유형(토사형 비점·유기물형 월류·희석형)을 가른다
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats

import config as C
from core import Report, io, st

REQUIRES = ["river_daily", "weather_daily", "weather_link"]
LEVEL = "연계"
VARS = ["TP", "TOC", "TN", "Turb"]
BASE_WIN = 31          # 건기 기준선 이동 창(일)


def classify(r):
    """사건 1건 판정: 탁도는 '건기 대비 배율', TP·TOC·TN 은 '희석 예상 대비 배율'(>1 이면 희석만으로 설명 안 되는 유입)"""
    turb = r.get("Turb", np.nan)
    tp, toc, tn = (r.get(f"{k}_희석초과", np.nan) for k in ["TP", "TOC", "TN"])
    soil = bool(turb >= 2) if not np.isnan(turb) else None      # None = 탁도 미측정
    org = (toc >= 1.2) or (tn >= 1.2)
    if soil and tp >= 1.3:
        return "토사형 비점(탁도·TP 동반 상승)"
    if org and not soil:
        return "유기물·질소형(하수 월류·축산 의심)"
    if soil:
        return "탁도 위주(토사·하상 재부유, 영양염 약함)" if not org else "토사+유기물 복합"
    if tp >= 1.3:
        return "TP 상승(탁도 미측정·약함)"
    vals = [x for x in [tp, toc, tn] if not np.isnan(x)]
    if vals and max(vals) <= 1.1:
        return "희석형(추가 유입 없음)"
    return "약한 유입(희석 예상의 1.1~1.3배)"


def main():
    rep = Report("44_wet_excess_load", "44. 강우 초과 부하: 희석 예상보다 높은 만큼이 강우 유래", level=LEVEL,
                 purpose="방류 TMS 는 비가 와도 거의 변하지 않는다(v2: 유량 +3.9%, 농도 −4%). 그런데 하천 농도가 오른다면 그 차이는 TMS 밖에서 온다. "
                         "'평상시보다 높다'가 아니라 '건기 부하가 그대로일 때 희석으로 예상되는 농도보다 높다'를 기준으로 삼고(유량이 있으면 유량, 없으면 전기전도도로 희석 비율 추정), "
                         "함께 오른 항목으로 비점(토사)과 하수 월류(유기물·질소)를 가른다. RESEARCH_REVIEW.md 방향 2.")
    w, sta = io.load_weather(), io.load_stations()
    if w is None or sta["weather_stn"].isna().all():
        return rep.wait("기상 자료 또는 측정소-기상지점 연결이 없다.", ["기상청 ASOS 일자료(자료요구서 B-1)"])
    R = w.pivot_table(index="date", columns="stn", values="rain_mm", aggfunc="first")
    f = io.load_flow()
    Q = f.pivot_table(index="date", columns="obscd", values="flow_cms", aggfunc="first") if f is not None else None
    tms = io.load_tms()
    if tms is not None:
        tms = tms.assign(date=pd.to_datetime(tms["date"]))
    d = io.load_daily(VARS + ["EC"], quality=False)
    links = sta.dropna(subset=["weather_stn"])
    links = links[links["weather_stn"].isin(R.columns)]
    d = d[d["station"].isin(links["station"])]
    rep.data_info(d)

    day_rows, ev_rows, tms_rows = [], [], []
    for _, lk in links.iterrows():
        stn = lk["station"]
        g = d[d["station"] == stn].set_index("date").asfreq("D")
        if g[VARS].notna().sum().max() < 200:
            continue
        rain = R[lk["weather_stn"]].reindex(g.index)
        r2 = rain.fillna(0) + rain.shift(1).fillna(0)
        event = (r2 >= C.EVENT_MM) & rain.notna()
        win = event | event.shift(1, fill_value=False)
        dry = rain.fillna(0).rolling(C.DRY_PRIOR_DAYS + 1).max() < C.WET_DAY_MM
        has_q = Q is not None and pd.notna(lk.get("flow_obscd")) and lk["flow_obscd"] in Q
        q = Q[lk["flow_obscd"]].reindex(g.index) if has_q else None
        base = lambda s: s.where(dry).rolling(BASE_WIN, center=True, min_periods=8).median()   # noqa: E731
        ec_b = base(g["EC"]) if "EC" in g else None
        q_b = base(q) if has_q else None
        if has_q:
            dil = (q_b / q).clip(upper=1)                       # 희석 비율(건기 부하 일정 가정)
            method = "유량"
        else:
            dil = (g["EC"] / ec_b).clip(upper=1) if ec_b is not None else pd.Series(np.nan, index=g.index)
            method = "EC"
        out = pd.DataFrame({"station": stn, "basin": g["basin"], "rain2d": r2, "event": event, "win": win, "희석비율": dil, "방법": method})
        for v in VARS:
            if g[v].notna().sum() < 150:
                continue
            cb = base(g[v])
            out[v] = g[v] / cb                                   # 관측 ÷ 건기 기준
            out[f"{v}_희석초과"] = g[v] / (cb * dil)              # 관측 ÷ 희석 예상
            if has_q and v != "Turb":                          # 탁도(NTU)는 질량 부하가 아님
                L, Lb = g[v] * q * 86.4, cb * q_b * 86.4
                out[f"{v}_초과부하kg"] = (L - Lb).where(win).clip(lower=0)
                out[f"{v}_부하kg"] = L
        day_rows.append(out[out["win"]].reset_index())
        # 사건 묶기(연속된 사건 창을 1건으로)
        o = out[out["win"]]
        if o.empty:
            continue
        grp = (o.index.to_series().diff() > pd.Timedelta(days=1)).cumsum()
        for k, e in o.groupby(grp.values):
            r = {"station": stn, "basin": lk["basin"],
                 "시작": e.index.min(), "2일강수max": e["rain2d"].max(), "방법": method, "희석비율": e["희석비율"].min()}
            for v in VARS:
                if v in e:
                    r[v] = e[v].max()
                    r[f"{v}_희석초과"] = e[f"{v}_희석초과"].max()
                    if f"{v}_초과부하kg" in e:
                        r[f"{v}_초과부하kg"] = e[f"{v}_초과부하kg"].sum()
            r["유형"] = classify(r)
            ev_rows.append(r)
        if tms is not None and pd.notna(lk.get("upstream_tms")):
            L = io.tms_upstream_load(tms, [s.strip() for s in str(lk["upstream_tms"]).split(";")])
            if L is not None:
                L = L.reindex(g.index)
                for col, nm in [("Q", "방류수량"), ("TP_load", "TP부하"), ("TOC_load", "TOC부하")]:
                    b = base(L[col])
                    tms_rows.append({"station": stn, "항목": nm, "사건일/건기": (L[col] / b)[win].median()})

    D, E = pd.concat(day_rows, ignore_index=True), pd.DataFrame(ev_rows)
    if E.empty:
        return rep.wait("연결된 측정소에 강우 사건이 없다.")
    rep.csv(E, "events.csv")

    rep.h("1. 사용자 기준 vs 수정 기준")
    rows = []
    for v in VARS:
        x = D.dropna(subset=[v])
        if len(x) < 30:
            continue
        rows.append({"항목": v, "사건일": len(x), "측정소": x["station"].nunique(),
                     "관측>평상시(사용자 기준)%": (x[v] > 1).mean() * 100,
                     "관측>희석예상(수정 기준)%": (x[f"{v}_희석초과"] > 1).mean() * 100,
                     "관측/평상시 중앙": x[v].median(), "관측/희석예상 중앙": x[f"{v}_희석초과"].median(),
                     "희석비율 중앙": x["희석비율"].median()})
    cmp_ = pd.DataFrame(rows)
    rep.table(cmp_.round(3))
    rep.p("희석비율 = 건기 부하가 그대로일 때 농도가 몇 배로 줄어야 하는가(유량 연결 측정소는 건기유량÷당일유량, 나머지는 EC 비). "
          "큰 하천은 하루 평균 희석비율이 1에 가까워(거의 안 묽어짐) '평상시보다 낮아야 한다'는 전제가 약하다. 수정 기준은 이 희석을 반영한다.")
    for r in cmp_.itertuples():
        rep.finding(f"강우 사건일 {r.항목}: 평상시보다 높은 날 {r._4:.0f}% → 희석 예상보다 높은 날 {r._5:.0f}% (관측/희석예상 중앙 ×{r._7:.2f})")

    rep.h("2. 사건 유형(함께 오른 항목으로 판정)")
    tab = E.pivot_table(index="유형", columns="basin", values="station", aggfunc="count", fill_value=0)
    tab["합계"] = tab.sum(axis=1)
    rep.table(tab.sort_values("합계", ascending=False), index=True)
    rep.p("판정은 '희석 예상 대비' 배율로 한다. 토사형 비점 = 탁도 ×2 이상(건기 대비)·TP 가 희석 예상의 1.3배 이상(농경지·공사장·도로 토사). "
          "유기물·질소형 = TOC 또는 TN 이 희석 예상의 1.2배 이상인데 탁도 상승은 작음 → "
          "합류식 월류·처리장 우회·축산 유출 의심(TMS 에 안 잡히는 하수). 시군 분류식 관로 비율(자료요구서 추가 항목)과 맞춰 보면 월류 여부를 좁힐 수 있다.")
    st_tab = E.pivot_table(index="station", columns="유형", values="시작", aggfunc="count", fill_value=0)
    rep.table(st_tab, "측정소별 사건 유형 수", index=True)
    rep.csv(st_tab.reset_index(), "event_types_by_station.csv")
    top = E["유형"].value_counts()
    rep.finding(f"강우 사건 {len(E)}건 유형: " + ", ".join(f"{k} {v}건" for k, v in top.items()))
    sew = st_tab.get("유기물·질소형(하수 월류·축산 의심)")
    if sew is not None and sew.max() > 0:
        rep.finding("유기물·질소형(월류·축산 의심) 사건이 많은 측정소: " + ", ".join(f"{k} {v}건" for k, v in sew.sort_values(ascending=False).head(4).items() if v > 0))

    exc_cols = [c for c in E.columns if c.endswith("_초과부하kg")]
    if exc_cols:
        rep.h("3. 강우 초과 부하(유량 연결 측정소)")
        rows = []
        for stn, g in D.groupby("station"):
            for v in VARS:
                if f"{v}_초과부하kg" in g and g[f"{v}_초과부하kg"].notna().any():
                    tot = d[d["station"] == stn]
                    rows.append({"station": stn, "항목": v, "사건일": int(g[f"{v}_초과부하kg"].notna().sum()),
                                 "초과부하 합(t)": g[f"{v}_초과부하kg"].sum() / 1000})
        ex = pd.DataFrame(rows)
        rep.table(ex.round(3))
        rep.p("초과부하 = (사건일 실제 부하) − (건기 기준 농도 × 건기 기준 유량). 비점·월류 등 강우 때만 생기는 부하의 추정치다.")
    if tms_rows:
        rep.h("4. 같은 날 상류 방류 TMS 는 얼마나 변했나")
        tt = pd.DataFrame(tms_rows).pivot_table(index="station", columns="항목", values="사건일/건기")
        rep.table(tt.round(3), index=True)
        rep.finding(f"강우 사건일 상류 방류 TMS: 방류수량 ×{tt['방류수량'].median():.2f}, TP 부하 ×{tt['TP부하'].median():.2f}(측정소 중앙) — 하천 농도 상승은 TMS 방류 탓이 아니다")

    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    x = D.dropna(subset=["TP", "TP_희석초과"])
    axes[0].scatter(x["희석비율"], x["TP"], s=6, alpha=0.5)
    axes[0].plot([0, 1], [0, 1], color="r", lw=1, label="희석만 됐을 때")
    axes[0].axhline(1, color="gray", lw=0.6)
    axes[0].set_xlabel("희석비율(1 = 안 묽어짐)")
    axes[0].set_ylabel("TP 관측 ÷ 건기 기준")
    axes[0].set_yscale("log")
    axes[0].legend()
    top.plot.barh(ax=axes[1])
    axes[1].set_xlabel("사건 수")
    fig.tight_layout()
    rep.fig(fig, "dilution_vs_observed.png", "빨간 선 위쪽 = 희석 예상보다 높음(강우 유래 유입)")
    rep.save()


if __name__ == "__main__":
    main()
