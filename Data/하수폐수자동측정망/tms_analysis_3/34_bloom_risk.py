# -*- coding: utf-8 -*-
"""
34. 조류 고농도 위험 — 발생 빈도, 로지스틱 회귀(오즈비·95%CI), 3일 앞 조기경보 성능(2024 학습 → 2025 검증, AUC·기후값 대비)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import config as C
from core import Report, io

REQUIRES = ["river_daily"]
LEVEL = "심화"
LEAD = 3
PRED = ["WT", "dWT7", "log_TP", "log_TN", "log_Turb", "log_EC", "log_Chl_a", "dDO"]


def auc(y, s):
    y, s = np.asarray(y), np.asarray(s)
    pos, neg = s[y == 1], s[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return np.nan
    r = pd.Series(np.concatenate([pos, neg])).rank().values
    return (r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def main():
    rep = Report("34_bloom_risk", "34. 조류 고농도 위험과 조기경보 가능성", level=LEVEL,
                 purpose="Chl-a 고농도일(절대 기준과 측정소별 상위 10%)이 언제·어디서 잦은지, 어떤 조건에서 확률이 오르는지(오즈비), "
                         f"그리고 오늘 자료로 {LEAD}일 뒤 고농도를 얼마나 맞힐 수 있는지(조기경보 성능)를 평가한다.")
    d = io.load_daily(["WT", "TP", "TN", "Turb", "EC", "Chl_a", "DO"], minmax=True)
    rep.data_info(d)
    rep.h(f"1. 고농도일 빈도(Chl-a ≥ {C.BLOOM_CHLA:g} mg/㎥)")
    x = d.dropna(subset=["Chl_a"])
    fr = x.groupby(["basin", "station"]).agg(일수=("Chl_a", "size"), 고농도일=("Chl_a", lambda s: int((s >= C.BLOOM_CHLA).sum())),
                                             p90=("Chl_a", lambda s: s.quantile(0.9))).reset_index()
    fr["비율%"] = fr["고농도일"] / fr["일수"] * 100
    fr = fr.sort_values("비율%", ascending=False)
    rep.table(fr.head(20))
    rep.csv(fr, "bloom_frequency.csv")
    rep.finding(f"Chl-a ≥ {C.BLOOM_CHLA:g} 일이 10% 넘는 측정소 {int((fr['비율%'] > 10).sum())}곳 — 최다 "
                + ", ".join(f"{a} {b:.0f}%" for a, b in zip(fr['station'].head(3), fr['비율%'].head(3))))
    mon = x.assign(b=x["Chl_a"] >= C.BLOOM_CHLA).groupby(["basin", "month"])["b"].mean().unstack(0) * 100
    rep.table(mon.round(1), "월별 고농도일 비율(%)", index=True)

    rows = []
    for stn, g in d.groupby("station"):
        g = g.set_index("date").sort_index().asfreq("D")
        if g["Chl_a"].notna().sum() < 300:
            continue
        f = pd.DataFrame(index=g.index)
        thr = g["Chl_a"].quantile(0.9)
        f["y_future"] = (g["Chl_a"].shift(-LEAD) >= thr).astype(float).where(g["Chl_a"].shift(-LEAD).notna())
        f["WT"] = g["WT"]
        f["dWT7"] = g["WT"] - g["WT"].shift(7)
        for v in ["TP", "TN", "Turb", "EC", "Chl_a"]:
            f[f"log_{v}"] = np.log(g[v].clip(lower=1e-3))
        f["dDO"] = g["DO_max"] - g["DO_min"]
        f["station"], f["basin"], f["year"] = stn, g["basin"].ffill().bfill(), f.index.year
        f["clim"] = np.nan
        rows.append(f)
    F = pd.concat(rows).reset_index()
    rep.h(f"2. {LEAD}일 뒤 고농도(측정소별 상위 10%) 예측 — 로지스틱 회귀")
    try:
        import statsmodels.api as sm
    except ImportError:
        return rep.wait("statsmodels 필요")
    out, ors = [], []
    yrs = sorted(F["year"].unique())
    for b in C.BASINS:
        x = F[F["basin"] == b]
        cols = [c for c in PRED if x[c].notna().mean() > 0.5]
        x = x.dropna(subset=cols + ["y_future"])
        if len(x) < 500 or x["y_future"].sum() < 30:
            continue
        mu, sd = x[cols].mean(), x[cols].std()
        z = (x[cols] - mu) / sd
        m = sm.Logit(x["y_future"], sm.add_constant(z)).fit(disp=0)
        ci = m.conf_int()
        for c in cols:
            ors.append({"수계": b, "변수(1 표준편차 증가)": c, "오즈비": np.exp(m.params[c]),
                        "95%CI": f"{np.exp(ci.loc[c, 0]):.2f}~{np.exp(ci.loc[c, 1]):.2f}", "p": m.pvalues[c]})
        if len(yrs) >= 2:
            tr, te = x[x["year"] < yrs[-1]], x[x["year"] == yrs[-1]]
            if len(te) > 100 and te["y_future"].sum() > 10:
                mm = sm.Logit(tr["y_future"], sm.add_constant((tr[cols] - mu) / sd)).fit(disp=0)
                p = mm.predict(sm.add_constant((te[cols] - mu) / sd))
                # 비교 기준: 같은 달 고농도 빈도(기후값)와 '오늘 Chl-a 만' 쓴 지속 모형
                clim = te["date"].dt.month.map(tr.groupby(tr["date"].dt.month)["y_future"].mean())
                pers = te["log_Chl_a"]
                out.append({"수계": b, "학습": f"~{yrs[-2]}", "검증": yrs[-1], "검증일": len(te), "고농도일": int(te["y_future"].sum()),
                            "AUC(모형)": auc(te["y_future"], p), "AUC(오늘 Chl-a 만)": auc(te["y_future"], pers),
                            "AUC(월 기후값)": auc(te["y_future"], clim.fillna(clim.mean()))})
    orr = pd.DataFrame(ors)
    rep.table(orr.round(3), "오즈비(표준화) — 1보다 크면 그 변수가 1 표준편차 오를 때 3일 뒤 고농도 확률이 커짐")
    rep.csv(orr, "odds_ratios.csv")
    ev = pd.DataFrame(out)
    rep.table(ev.round(3), f"{LEAD}일 앞 조기경보 성능(시간 분할 검증)")
    for r in ev.itertuples():
        gain = r._6 - r._7
        rep.finding(f"{r.수계} {LEAD}일 앞 조류 고농도 예측 AUC {r._6:.2f} (오늘 Chl-a 만 {r._7:.2f}, 월 기후값 {r._8:.2f}) — "
                    + ("수질·수온 정보가 경보 정확도를 높임" if gain > 0.02 else "오늘 Chl-a 지속성만으로도 대부분 설명"))
    rep.p("AUC 0.5 = 무작위, 0.7 이상 쓸 만함, 0.8 이상 좋음. 검증은 마지막 연도를 통째로 떼어 미래 예측처럼 평가했다.")
    rep.save()


if __name__ == "__main__":
    main()
