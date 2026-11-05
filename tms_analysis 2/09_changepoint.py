# -*- coding: utf-8 -*-
"""
09. 변화점 탐지(Change-point) — v2
[v2 변경] v1은 장마 시작·가을 전환 같은 '계절 변화'를 변화점으로 잡았다.
  → 주 단위 로그 시계열에서 '월별 평균 계절 성분'을 먼저 빼고 탐지
  → 벌점(PENALTY)을 자료 길이에 비례(BIC형)하게 올리고, 최소 구간을 12주로 늘림
  → 직전·직후 12주 수준 차이가 MIN_CHANGE_PCT 미만이면 버림
- 같은 사업장에서 여러 항목이 같은 시기에 바뀜 → 공정 변경·증설 후보
- 여러 사업장이 같은 주에 바뀜 → 측정·전송 체계 변경 후보
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import config as C
from common import Report, load_clean, valid_sids, daily, need

VARS = ["Q", "TOC", "SS", "TN", "TP", "pH"]
PEN_FACTOR = 3.0      # 벌점 = PEN_FACTOR × log(n). 클수록 변화점이 적게 잡힘
MIN_SIZE = 12         # 구간 최소 길이(주)
WIN = 12              # 변화 전후 비교 창(주)
MIN_CHANGE_PCT = 20   # 이보다 작은 수준 변화는 버림(pH는 2%)


def binseg(x, pen, min_size=MIN_SIZE):
    """간이 이분 분할(평균 변화, 표준화 자료) — ruptures 가 없을 때 사용"""
    cps = []

    def cost(a):
        return ((a - a.mean()) ** 2).sum() if len(a) else 0.0

    def split(lo, hi):
        seg = x[lo:hi]
        if len(seg) < 2 * min_size:
            return
        base = cost(seg)
        best, bk = 0, None
        for k in range(min_size, len(seg) - min_size):
            gain = base - cost(seg[:k]) - cost(seg[k:])
            if gain > best:
                best, bk = gain, k
        if bk is not None and best > pen:
            cps.append(lo + bk)
            split(lo, lo + bk)
            split(lo + bk, hi)

    split(0, len(x))
    return sorted(cps)


def detect(x):
    pen = PEN_FACTOR * np.log(len(x))
    rpt = need("ruptures")
    if rpt is not None:
        algo = rpt.Pelt(model="l2", min_size=MIN_SIZE).fit(x.reshape(-1, 1))
        return [b for b in algo.predict(pen=pen) if b < len(x)]
    return binseg(x, pen)


def deseasonalize(s, is_log):
    """주 단위 시계열에서 '달별 평균'(여러 해 평균)을 뺀 값"""
    x = np.log(s) if is_log else s.copy()
    clim = x.groupby(x.index.month).transform("mean")
    return x - clim + x.mean()


def main():
    rep = Report("09_changepoint", "09. 변화점 탐지(v2, 계절 제거 후)",
                 "계절 변화를 뺀 뒤에도 남는 '계단식 수준 변화'(공법 변경, 증설, 센서 교체·교정 등)를 찾는다.")
    df = load_clean()
    sids = valid_sids(df, "TN", min_days=500)
    df = df[df["sid"].isin(sids)]

    rows = []
    for sid, g in df.groupby("sid"):
        for v in VARS:
            s = daily(g, v).resample("W").median().interpolate(limit=2).dropna()
            if len(s) < 3 * MIN_SIZE:
                continue
            is_log = v != "pH" and (s > 0).all()
            ds = deseasonalize(s, is_log)
            x = ds.values
            mad = np.median(np.abs(x - np.median(x))) * 1.4826
            z = (x - np.median(x)) / (mad if mad > 0 else (x.std() + 1e-9))
            for b in detect(z):
                lv_b = ds.iloc[max(0, b - WIN):b].median()
                lv_a = ds.iloc[b:b + WIN].median()
                pct = (np.exp(lv_a - lv_b) - 1) * 100 if is_log else (lv_a / lv_b - 1) * 100
                thr = 2 if v == "pH" else MIN_CHANGE_PCT
                if abs(pct) < thr:
                    continue
                rows.append({"sid": sid, "시군": g["sigun"].iloc[0], "항목": v, "변화주": s.index[b],
                             "직전12주_원값": s.iloc[max(0, b - WIN):b].median(),
                             "직후12주_원값": s.iloc[b:b + WIN].median(),
                             "계절제거_변화율_pct": pct})
    cp = pd.DataFrame(rows)
    rep.csv(cp, "changepoints_long.csv")
    rep.kv({"분석 방류구": len(sids), "변화점 수": len(cp),
            "방류구·항목당 평균": len(cp) / max(1, len(sids) * len(VARS)),
            "설정": f"벌점 {PEN_FACTOR}×log(n), 최소구간 {MIN_SIZE}주, 최소변화 {MIN_CHANGE_PCT}%"})
    if cp.empty:
        rep.p("변화점이 없습니다(PEN_FACTOR 또는 MIN_CHANGE_PCT 를 낮춰 보세요).")
        rep.save()
        return

    cp["abs_pct"] = cp["계절제거_변화율_pct"].abs()
    rep.h("1. 항목별 변화점 수")
    rep.table(cp.groupby("항목").agg(변화점수=("sid", "size"), 방류구수=("sid", "nunique"),
                                   변화율절대값_중앙=("abs_pct", "median")).reset_index())

    rep.h("2. 큰 변화(|변화율| 상위 30)")
    rep.table(cp.sort_values("abs_pct", ascending=False).drop(columns="abs_pct").head(30))

    rep.h("3. 같은 방류구에서 3개 이상 항목이 ±3주 안에 바뀐 경우 → 공정·운영 변화 후보")
    multi = []
    for sid, g in cp.groupby("sid"):
        g = g.sort_values("변화주")
        for _, r in g.iterrows():
            near = g[(g["변화주"] - r["변화주"]).abs() <= pd.Timedelta(weeks=3)]
            if near["항목"].nunique() >= 3:
                multi.append({"sid": sid, "시군": r["시군"], "변화주": r["변화주"],
                              "항목": ",".join(sorted(near["항목"].unique()))})
    mt = pd.DataFrame(multi).drop_duplicates(["sid", "항목"]) if multi else pd.DataFrame()
    rep.table(mt, max_rows=40)
    rep.csv(mt, "multi_param_changes.csv")

    rep.h("4. 여러 방류구가 같은 주에 바뀐 경우 → 광역 요인 후보")
    wk = cp.groupby(["변화주", "항목"])["sid"].nunique().reset_index(name="방류구수")
    rep.table(wk.sort_values("방류구수", ascending=False).head(25))
    rep.p("계절을 뺐는데도 많은 방류구가 같은 주에 바뀌면, 기상 극값(집중호우 직후)이나 측정·전송 체계 변경을 의심한다.")

    fig, ax = plt.subplots(figsize=(13, 3.5))
    for v in VARS:
        h = cp[cp["항목"] == v].groupby("변화주").size()
        ax.plot(h.index, h.values, marker=".", lw=0.6, label=v)
    ax.legend(ncol=6)
    ax.set_title("주별 변화점 수(계절 제거 후)")
    rep.fig(fig, "changepoints_by_week.png")

    rep.save()


if __name__ == "__main__":
    main()
