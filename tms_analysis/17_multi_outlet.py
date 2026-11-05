# -*- coding: utf-8 -*-
"""
17. 다중 방류구 사업장 비교
- 방류구가 2개 이상인 사업장에서 방류구별 유량 분담, 농도 차이(같은 날 대응 비교, Wilcoxon), 변동성 차이
- 방류구끼리 일 편차가 같이 움직이는지(같은 유입·다른 계열 vs 다른 처리구역)
- 가끔만 가동되는 방류구(가동일 비율 낮음, 고유량일에 몰림) → 강우시 계통·비상 방류구 후보
- 사업장 합산 유량가중 농도
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats

import config as C
from common import Report, load_clean, daily, anomaly


def main():
    rep = Report("17_multi_outlet", "17. 다중 방류구 사업장 비교",
                 "한 사업장 안 방류구들의 역할 차이(주 계열, 증설 계열, 강우시 계통 등)를 자료로 추정한다.")
    df = load_clean()
    multi = df.groupby("site")["outlet"].nunique()
    multi = multi[multi >= 2].index
    df = df[df["site"].isin(multi)]
    rep.kv({"방류구 2개 이상 사업장 수": len(multi)})

    rows, pair_rows = [], []
    for site, g in df.groupby("site"):
        span = pd.date_range(g["date"].min(), g["date"].max(), freq="D")
        Qw = g.pivot_table(index="date", columns="outlet", values="Q").reindex(span)
        tot = Qw.sum(axis=1, min_count=1)
        site_p95 = tot.quantile(0.95)
        for o, s in Qw.items():
            gg = g[g["outlet"] == o]
            active = s.notna() & (s > 0)
            r = {"사업장": site, "방류구": o, "시군": g["sigun"].iloc[0],
                 "가동일비율_pct": active.mean() * 100,
                 "유량분담_pct": s.sum() / tot.sum() * 100 if tot.sum() else np.nan,
                 "Q중앙": s.median(), "Q_CV": s.std() / s.mean() if s.mean() else np.nan,
                 "고유량일_가동비율_pct": active[tot >= site_p95].mean() * 100,
                 "평상일_가동비율_pct": active[tot < tot.median()].mean() * 100}
            for p in C.PARAMS:
                r[f"{p}_중앙"] = gg[p].median()
            rows.append(r)
        outs = sorted(g["outlet"].unique())
        for i, a in enumerate(outs):
            for b in outs[i + 1:]:
                ga, gb = g[g["outlet"] == a].set_index("date"), g[g["outlet"] == b].set_index("date")
                pr = {"사업장": site, "방류구A": a, "방류구B": b}
                for v in ["Q"] + C.PARAMS:
                    j = pd.concat([ga[v], gb[v]], axis=1, keys=["a", "b"]).dropna()
                    if len(j) < 60:
                        continue
                    pr[f"{v}_A/B중앙비"] = (j["a"] / j["b"]).median()
                    try:
                        pr[f"{v}_Wilcoxon_p"] = stats.wilcoxon(j["a"], j["b"]).pvalue
                    except ValueError:
                        pr[f"{v}_Wilcoxon_p"] = np.nan
                    aa = anomaly(ga[v].asfreq("D"))
                    bb = anomaly(gb[v].asfreq("D"))
                    pr[f"{v}_편차상관"] = aa.corr(bb)
                pair_rows.append(pr)
    t = pd.DataFrame(rows)
    pr = pd.DataFrame(pair_rows)
    rep.csv(t, "outlet_stats.csv")
    rep.csv(pr, "outlet_pairs.csv")

    rep.h("1. 방류구별 역할 요약")
    rep.table(t.sort_values(["사업장", "방류구"]), max_rows=80)

    rep.h("2. 간헐 가동 방류구(강우시·비상 계통 후보)")
    inter = t[(t["가동일비율_pct"] < 80) | (t["고유량일_가동비율_pct"] - t["평상일_가동비율_pct"] > 20)]
    rep.table(inter.sort_values("가동일비율_pct")[["사업장", "방류구", "가동일비율_pct", "유량분담_pct",
                                                 "고유량일_가동비율_pct", "평상일_가동비율_pct", "Q_CV"]])

    rep.h("3. 방류구 쌍 비교")
    if not pr.empty:
        cols = ["사업장", "방류구A", "방류구B"] + [c for c in pr.columns if c.endswith("편차상관") or c.endswith("A/B중앙비")]
        rep.table(pr[cols], max_rows=60, digits=2)
        rep.table(pr[[c for c in pr.columns if c.endswith("편차상관")]].describe().T.reset_index().rename(columns={"index": "지표"}),
                  "방류구 간 편차 상관 분포", digits=2)
        rep.p("유량 편차상관이 높으면 같은 유입을 나눠 받는 병렬 계열, 낮으면 처리구역·유입원이 다른 계열 가능성. "
              "TN·TP 중앙비가 1에서 멀면 계열별 공정 성능 차이.")

    if not t.empty:
        fig, ax = plt.subplots(figsize=(6, 4.5))
        ax.scatter(t["가동일비율_pct"], t["Q_CV"], s=14)
        ax.set_xlabel("가동일 비율(%)")
        ax.set_ylabel("유량 CV")
        ax.set_title("방류구 가동 빈도와 변동성")
        rep.fig(fig, "outlet_activity_vs_cv.png")

    rep.save()


if __name__ == "__main__":
    main()
