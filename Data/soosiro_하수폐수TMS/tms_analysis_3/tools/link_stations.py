# -*- coding: utf-8 -*-
"""
측정소 좌표(lat/lon)가 채워지면, 가장 가까운 기상 지점·유량 관측소를 계산해 연결 '제안표'를 만든다.

    python tools/link_stations.py              → data/meta/stations_link_suggest.csv (제안만, 원본은 그대로)
    python tools/link_stations.py --apply      → 비어 있는 weather_stn·flow_obscd 칸만 제안값으로 채움
    python tools/link_stations.py --apply --overwrite   → '추정' 값도 제안값으로 교체

거리 기준: 기상 config 없음 → 30 km 이내 가장 가까운 ASOS(kind=weather), 유량 → 5 km 이내 같은 이름 하천 우선 아님(거리만).
좌표 출처: 물환경정보시스템 측정소 정보(자료요구서 A-1). obs_stations.csv 는 02번이 만든다.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from core import schema  # noqa: E402

MAX_KM = {"weather": 30, "flow": 5}


def hav(lat1, lon1, lat2, lon2):
    p = np.pi / 180
    a = np.sin((lat2 - lat1) * p / 2) ** 2 + np.cos(lat1 * p) * np.cos(lat2 * p) * np.sin((lon2 - lon1) * p / 2) ** 2
    return 12742 * np.arcsin(np.sqrt(a))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args()
    st = schema.read("stations")
    if st["lat"].isna().all():
        sys.exit("stations.csv 에 측정소 좌표(lat, lon)가 없습니다. 자료요구서 A-1 의 측정소 정보를 먼저 넣으세요.")
    obs = schema.read("obs_stations").dropna(subset=["lat", "lon"])
    rows = []
    for _, r in st.dropna(subset=["lat", "lon"]).iterrows():
        out = {"station": r["station"]}
        for kind, col in [("weather", "weather_stn"), ("flow", "flow_obscd")]:
            o = obs[obs["kind"] == kind]
            if o.empty:
                continue
            dist = hav(r["lat"], r["lon"], o["lat"].values, o["lon"].values)
            i = int(np.argmin(dist))
            if dist[i] <= MAX_KM[kind]:
                out[f"{col}_제안"], out[f"{col}_이름"], out[f"{col}_거리km"] = o["code"].iloc[i], o["name"].iloc[i], round(dist[i], 1)
        rows.append(out)
    sug = pd.DataFrame(rows)
    path = BASE / "data" / "meta" / "stations_link_suggest.csv"
    sug.to_csv(path, index=False, encoding="utf-8-sig")
    print(sug.to_string(index=False))
    print(f"\n[저장] {path}")
    if a.apply:
        m = st.merge(sug, on="station", how="left")
        for col in ["weather_stn", "flow_obscd"]:
            if f"{col}_제안" not in m:
                continue
            fill = m[f"{col}_제안"].notna() & (m[col].isna() | a.overwrite)
            m.loc[fill, col] = m.loc[fill, f"{col}_제안"]
            m.loc[fill, "link_note"] = m.loc[fill, "link_note"].fillna("") + f"; {col} 좌표 기반 자동"
        schema.write(m[st.columns], "stations", mode="replace")


if __name__ == "__main__":
    main()
