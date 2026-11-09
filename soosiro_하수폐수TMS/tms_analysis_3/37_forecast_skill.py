# -*- coding: utf-8 -*-
"""
37. 예측 가능성 — 1·3·7일 앞 예측: 지속(오늘값)·기후값 대비 그래디언트 부스팅의 기술점수(Skill), 시간 순 검증
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
TARGETS = ["Chl_a", "TOC", "TP", "DO"]
HORIZONS = [1, 3, 7]
DRIVERS = ["WT", "EC", "Turb", "TP", "Chl_a", "DO", "TOC"]


def make(g, v, h):
    f = pd.DataFrame(index=g.index)
    lg = (lambda s: np.log(s.clip(lower=1e-3))) if v in C.LOG_VARS else (lambda s: s)
    y = lg(g[v])
    f["y"] = y.shift(-h)
    for k in [0, 1, 2, 3, 7]:
        f[f"y_l{k}"] = y.shift(k)
    for dv in DRIVERS:
        if dv != v and dv in g:
            f[f"{dv}"] = (np.log(g[dv].clip(lower=1e-3)) if dv in C.LOG_VARS else g[dv])
            f[f"{dv}_d3"] = f[dv] - f[dv].shift(3)
    f["doy_s"], f["doy_c"] = np.sin(2 * np.pi * g.index.dayofyear / 365.25), np.cos(2 * np.pi * g.index.dayofyear / 365.25)
    f["clim"] = y.groupby(y.index.month).transform("mean")
    return f


def main():
    rep = Report("37_forecast_skill", "37. 며칠 앞까지 예측할 수 있나(예측 기술점수)", level=LEVEL,
                 purpose="자동측정망 자료만으로 1·3·7일 뒤 수질을 '오늘 값 그대로(지속)'보다 잘 맞힐 수 있는지 측정소마다 시험한다. "
                         "기술점수(Skill) = 1 − 모형오차/지속오차. 양수면 모형이 낫다. 조기경보 체계 설계의 근거가 된다.")
    try:
        from sklearn.ensemble import HistGradientBoostingRegressor
    except ImportError:
        return rep.wait("scikit-learn 필요")
    d = io.load_daily(DRIVERS)
    rep.data_info(d)
    rows = []
    for (b, stn), g in d.groupby(["basin", "station"]):
        g = g.set_index("date").sort_index().asfreq("D")
        for v in TARGETS:
            if g[v].notna().sum() < 450:
                continue
            for h in HORIZONS:
                f = make(g, v, h).dropna(subset=["y", "y_l0"])
                if len(f) < 400:
                    continue
                cut = int(len(f) * 0.6)             # 앞 60% 학습 → 뒤 40% 검증(시간 순)
                tr, te = f.iloc[:cut], f.iloc[cut:]
                X = [c for c in f.columns if c not in ("y", "clim") and tr[c].notna().mean() > 0.2]   # 측정 안 하는 항목 제외
                # 오늘 값에서 '얼마나 바뀔지'를 학습(지속 예측 + 보정) → 자료가 적어도 지속보다 크게 나빠지지 않게
                m = HistGradientBoostingRegressor(max_iter=150, learning_rate=0.03, max_leaf_nodes=8, min_samples_leaf=40,
                                                  l2_regularization=1.0, random_state=C.RANDOM_STATE).fit(tr[X], tr["y"] - tr["y_l0"])
                mae_m = np.mean(np.abs(te["y"] - (te["y_l0"] + m.predict(te[X]))))
                mae_p = np.mean(np.abs(te["y"] - te["y_l0"]))
                mae_c = np.mean(np.abs(te["y"] - te["clim"]))
                rows.append({"basin": b, "station": stn, "var": v, "h(일)": h, "검증일": len(te),
                             "MAE 모형": mae_m, "MAE 지속": mae_p, "MAE 기후": mae_c,
                             "Skill(대 지속)": 1 - mae_m / mae_p if mae_p else np.nan,
                             "Skill(대 기후)": 1 - mae_m / mae_c if mae_c else np.nan})
    t = pd.DataFrame(rows)
    rep.csv(t, "forecast_skill.csv")
    rep.h("1. 항목·예측일수별 기술점수(측정소 중앙)")
    s = t.groupby(["var", "h(일)"]).agg(측정소=("station", "size"), Skill_지속=("Skill(대 지속)", "median"),
                                       Skill_기후=("Skill(대 기후)", "median"),
                                       모형우세비율=("Skill(대 지속)", lambda x: (x > 0.05).mean())).round(3)
    rep.table(s, index=True)
    rep.p("로그 항목(Chl-a·TOC·TP)의 MAE 는 로그 단위(≈ 상대오차)다. 1일 앞은 지속이 매우 강해 모형 이득이 작고, "
          "예측일수가 길수록 수온·EC·탁도 같은 '선행 신호'의 가치가 커진다.")
    for v in TARGETS:
        x = s.loc[v] if v in s.index.get_level_values(0) else None
        if x is not None and 7 in x.index:
            rep.finding(f"{v} 7일 앞 예측: 지속 대비 기술점수 중앙 {x.loc[7, 'Skill_지속']:+.2f}, 기후값 대비 {x.loc[7, 'Skill_기후']:+.2f} "
                        f"(모형 우세 측정소 {x.loc[7, '모형우세비율']:.0%})")
    med = t["Skill(대 지속)"].median()
    rep.finding(f"전체 기술점수(대 지속) 중앙 {med:+.2f} — " + ("현재 자료(측정소당 학습 약 1.2년)로는 '오늘 값 유지'를 넘기 어렵다. "
                "다년 자료 누적·기상예보(강수·기온) 결합이 예측 개선의 조건" if med < 0.05 else "모형이 지속 예측보다 낫다"))
    best = t[(t["h(일)"] == 7)].sort_values("Skill(대 지속)", ascending=False).head(10)
    rep.table(best[["basin", "station", "var", "Skill(대 지속)", "Skill(대 기후)"]], "7일 앞 예측이 특히 잘 되는 측정소×항목")
    fig, ax = plt.subplots(figsize=(7, 4))
    for v in TARGETS:
        if v in s.index.get_level_values(0):
            ax.plot(s.loc[v].index, s.loc[v]["Skill_지속"], marker="o", label=v)
    ax.axhline(0, color="gray")
    ax.set_xlabel("예측 일수")
    ax.set_ylabel("기술점수(대 지속)")
    ax.legend()
    rep.fig(fig, "skill_by_horizon.png")
    rep.save()


if __name__ == "__main__":
    main()
