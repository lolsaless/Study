# -*- coding: utf-8 -*-
"""
10. 자료 품질 진단 — 결측·고정값·급변·ND·부분측정일, 측정소×항목 품질등급(A~D), 동시 결측일
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import config as C
from core import Report, io, st, schema

REQUIRES = ["river_daily"]
LEVEL = "기본"
VARS = C.CORE_VARS


def runs_equal(s, min_run):
    """같은 값이 min_run 이상 연속된 칸 비율"""
    x = s.dropna()
    if len(x) < min_run:
        return 0.0
    grp = (x != x.shift()).cumsum()
    size = x.groupby(grp).transform("size")
    return float((size >= min_run).mean())


def main():
    rep = Report("10_data_quality", "10. 자료 품질 진단", level=LEVEL,
                 purpose="분석에 앞서 측정소×항목별로 믿고 쓸 수 있는 자료인지 판정하고(A~D), 이후 분석의 사용 목록을 만든다.")
    raw = schema.read("river_daily")
    d = io.load_daily(VARS, quality=False)
    rep.data_info(d)
    hourly = io.load_hourly()

    rows = []
    for (b, stn), g in raw.groupby(["basin", "station"]):
        g = g.set_index("date").sort_index()
        cal = (g.index.max() - g.index.min()).days + 1
        for v in VARS:
            if f"{v}_n" not in g or (g[f"{v}_n"] > 0).sum() == 0:
                continue
            n = g[f"{v}_n"]
            full = g[f"{v}_mean"].where(n >= C.MIN_HOURS).asfreq("D")
            dz = full.diff()
            z = st.robust_z(dz)
            nd = g[f"{v}_nd"].sum() if f"{v}_nd" in g else 0
            r = {"basin": b, "station": stn, "var": v,
                 "유효일": int(full.notna().sum()), "커버리지%": full.notna().sum() / cal * 100,
                 "부분측정일%": float(((n > 0) & (n < C.MIN_HOURS)).sum() / max((n > 0).sum(), 1) * 100),
                 "고정값%": runs_equal(full, C.FLATLINE_MIN_DAYS) * 100,
                 "급변%": float((z.abs() > C.SPIKE_Z).mean() * 100),
                 "ND시간%": float(nd / max(n.sum() + nd, 1) * 100),
                 "최장결측(일)": int(full.isna().astype(int).groupby(full.notna().cumsum()).sum().max())}
            rows.append(r)
    q = pd.DataFrame(rows)
    if hourly is not None:
        fl = []
        for (stn), g in hourly.groupby("station"):
            for v in VARS:
                if v in g and g[v].notna().sum() > 500:
                    fl.append({"station": stn, "var": v, "시간고정값%": runs_equal(g[v].reset_index(drop=True), C.FLATLINE_MIN_RUN) * 100})
        q = q.merge(pd.DataFrame(fl), on=["station", "var"], how="left")
    # 등급은 '일평균 고정값'으로 판정한다. 시간자료 고정값은 0.1 단위로 기록되는 저농도 항목(탁도·TOC·pH)에서
    # 정상적으로도 길게 나타나므로 참고로만 보고한다. 급변은 물리적으로 매끄러운 항목(수온·pH·EC·DO)에만 적용
    flat = q["고정값%"]
    spike = q["급변%"].where(q["var"].isin(["WT", "pH", "EC", "DO"]), 0)
    q["등급"] = np.select(
        [(q["커버리지%"] >= 85) & (flat < 2) & (spike < 0.5),
         (q["커버리지%"] >= 70) & (flat < 5) & (spike < 1),
         (q["커버리지%"] >= 50) & (flat < 15)], ["A", "B", "C"], "D")
    q["분석사용"] = q["등급"].isin(["A", "B", "C"]) & (q["유효일"] >= C.MIN_DAYS)
    rep.csv(q, "quality_by_station_var.csv")
    C.WORK_DIR.mkdir(exist_ok=True)
    q.to_csv(C.WORK_DIR / "usable_pairs.csv", index=False, encoding="utf-8-sig")

    rep.h("1. 품질등급 분포(측정소×항목)")
    tab = q.pivot_table(index="var", columns="등급", values="station", aggfunc="count", fill_value=0).reindex(VARS)
    rep.table(tab, index=True)
    rep.p("A: 커버리지≥85%·고정값<2%·급변<0.5% / B: ≥70%·<5%·<1% / C: ≥50%·<15% / D: 그 밖. "
          "고정값 = 일평균이 5일 이상 같은 값(시간자료 72시간 고정은 참고값). 급변은 수온·pH·EC·DO 에만 적용. 분석사용 = A~C 이면서 유효일 ≥ MIN_DAYS")
    n_use = int(q["분석사용"].sum())
    rep.finding(f"측정소×항목 {len(q)}쌍 중 {n_use}쌍({n_use / len(q):.0%})을 분석에 사용(A {int((q['등급'] == 'A').sum())}, D {int((q['등급'] == 'D').sum())})")

    rep.h("2. 문제가 큰 측정소×항목")
    worst = q.sort_values(["커버리지%"]).head(15)
    rep.table(worst[["basin", "station", "var", "등급", "커버리지%", "고정값%", "급변%", "최장결측(일)"]], "커버리지 하위 15")
    flt = q.sort_values("고정값%", ascending=False).head(10)
    cols = ["basin", "station", "var", "고정값%"] + (["시간고정값%"] if "시간고정값%" in q else [])
    rep.table(flt[cols], "일평균 고정값(센서 정지·대체값 의심) 상위 10")
    if (flt["고정값%"] > 5).any():
        top = flt.iloc[0]
        rep.finding(f"일평균 고정값 구간 최대: {top['station']} {top['var']} {top['고정값%']:.0f}% — 센서 정지·대체값 여부 확인 필요")
    tp = q[(q["var"] == "TP") & (q["ND시간%"] > 5)].sort_values("ND시간%", ascending=False)
    if len(tp):
        rep.table(tp[["basin", "station", "ND시간%", "등급"]], "TP 검출한계 미만(ND)이 5% 넘는 측정소 — 일평균이 과대평가될 수 있음")
        rep.finding(f"TP ND 시간이 5%를 넘는 측정소 {len(tp)}곳(최대 {tp.iloc[0]['station']} {tp.iloc[0]['ND시간%']:.0f}%) — 저농도 하천의 TP 평균은 상향 편향")

    rep.h("3. 동시 결측일(측정망 전체 장애·자료 미확정 의심)")
    pres = d.assign(ok=d[VARS].notna().any(axis=1)).pivot_table(index="date", columns="station", values="ok", aggfunc="first")
    pres = pres.reindex(pd.date_range(d["date"].min(), d["date"].max())).fillna(False).infer_objects()
    share = 1 - pres.mean(axis=1)
    out = share[share > 0.3]
    rep.kv({"측정소 30% 이상이 동시에 결측인 날": len(out)})
    if len(out):
        rep.table(out.rename("결측비율").reset_index().rename(columns={"index": "date"}).head(20), "동시 결측일(상위 20)")

    rep.h("4. 월별 자료 보유율")
    mon = d.assign(ym=d["date"].dt.to_period("M"), ok=d[VARS].notna().mean(axis=1))
    hm = mon.pivot_table(index="station", columns="ym", values="ok", aggfunc="sum")
    days = mon.groupby("ym")["date"].apply(lambda s: s.dt.days_in_month.iloc[0])
    hm = (hm / days).clip(0, 1).fillna(0)
    order = d.drop_duplicates("station").sort_values(["basin", "station"])["station"]
    hm = hm.reindex(order)
    fig, ax = plt.subplots(figsize=(14, max(6, len(hm) * 0.18)))
    im = ax.imshow(hm.values, aspect="auto", cmap="viridis", vmin=0, vmax=1)
    ax.set_yticks(range(len(hm)), hm.index, fontsize=6)
    ax.set_xticks(range(0, hm.shape[1], 3), [str(c) for c in hm.columns[::3]], rotation=90, fontsize=7)
    fig.colorbar(im, ax=ax, label="핵심 9항목 보유율")
    rep.fig(fig, "coverage_heatmap.png", "측정소×월 자료 보유율(핵심 9항목 평균)")
    rep.save()


if __name__ == "__main__":
    main()
