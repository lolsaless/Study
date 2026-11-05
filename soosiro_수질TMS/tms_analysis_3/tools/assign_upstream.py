# -*- coding: utf-8 -*-
"""
지도 좌표로 '측정소 상류 구역 안의 TMS 사업장'을 자동 배정 (연구 방향 1의 구역 설정)

준비물
  1) 구역 경계: data/raw/gis/ 에 표준유역·중권역 경계 파일(.geojson 권장, .shp 는 geopandas 필요)
     - 물환경정보시스템 또는 WAMIS 에서 받은 표준유역(또는 오염총량 단위유역) 경계. 좌표계는 WGS84(EPSG:4326)로 저장
     - 구역 코드 열 이름은 --code-col 로 지정(예: SBSNCD, MB_ID)
  2) 측정소별 상류 구역 목록: data/meta/station_catchment.csv
       station,catchment_codes
       경안천,100601;100602;100603
     (측정소가 있는 구역 + 그 상류 구역 코드들. 모르면 '측정소가 있는 구역 하나'만 넣어도 된다)
     → --auto 를 주면 측정소 좌표(stations.csv lat/lon)가 들어 있는 구역 1개를 자동으로 채운다(상류 구역은 사람이 추가)
  3) TMS 사업장 좌표: config.TMS_SITE_COORDS (tms_analysis_2/data/site_coords.csv: site, lat, lon)

실행
  python tools/assign_upstream.py --code-col SBSNCD --auto         (station_catchment.csv 초안 만들기)
  python tools/assign_upstream.py --code-col SBSNCD                (배정 결과 제안표 → data/meta/upstream_suggest.csv)
  python tools/assign_upstream.py --code-col SBSNCD --apply        (stations.csv 의 upstream_tms 를 덮어씀, link_note 에 기록)
결과는 tools/make_map.py 로 지도에서 확인한다.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
import config as C  # noqa: E402
from core import schema  # noqa: E402
from matplotlib.path import Path as MPath  # noqa: E402


def load_polygons(code_col):
    """{구역코드: [matplotlib Path, …]}"""
    files = sorted(list(C.GIS_DIR.glob("*.geojson")) + list(C.GIS_DIR.glob("*.json")) + list(C.GIS_DIR.glob("*.shp")))
    if not files:
        sys.exit(f"{C.GIS_DIR} 에 경계 파일(.geojson/.shp)이 없습니다(자료요구서 A-3).")
    f = files[0]
    if f.suffix == ".shp":
        try:
            import geopandas as gpd
        except ImportError:
            sys.exit(".shp 는 geopandas 가 필요합니다(pip install geopandas). 또는 QGIS 에서 GeoJSON(EPSG:4326)으로 저장하세요.")
        gj = json.loads(gpd.read_file(f).to_crs(4326).to_json())
    else:
        gj = json.loads(f.read_text(encoding="utf-8"))
    polys = {}
    for ft in gj["features"]:
        code = str(ft["properties"].get(code_col))
        geom = ft["geometry"]
        rings = geom["coordinates"] if geom["type"] == "Polygon" else [p[0] for p in geom["coordinates"]]
        if geom["type"] == "Polygon":
            rings = [rings[0]]
        polys.setdefault(code, []).extend(MPath(np.asarray(r)[:, :2]) for r in rings)
    print(f"[경계] {f.name}: 구역 {len(polys)}개 (코드 열 {code_col})")
    return polys


def which(polys, lon, lat):
    for code, ps in polys.items():
        if any(p.contains_point((lon, lat)) for p in ps):
            return code
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code-col", required=True)
    ap.add_argument("--auto", action="store_true", help="측정소가 있는 구역으로 station_catchment.csv 초안 생성")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    polys = load_polygons(a.code_col)
    st = schema.read("stations")
    if a.auto:
        x = st.dropna(subset=["lat", "lon"])
        if x.empty:
            sys.exit("stations.csv 에 측정소 좌표가 없습니다(자료요구서 A-1).")
        out = pd.DataFrame({"station": x["station"], "catchment_codes": [which(polys, r.lon, r.lat) for r in x.itertuples()]})
        if C.STATION_CATCHMENT_CSV.exists():
            print(f"이미 있음: {C.STATION_CATCHMENT_CSV} — 덮어쓰지 않고 초안을 _draft 로 저장")
            path = C.STATION_CATCHMENT_CSV.with_name("station_catchment_draft.csv")
        else:
            path = C.STATION_CATCHMENT_CSV
        out.to_csv(path, index=False, encoding="utf-8-sig")
        print(out.to_string(index=False), f"\n[저장] {path}\n→ 각 측정소에 상류 구역 코드를 ; 로 추가한 뒤 --apply 없이 다시 실행해 확인")
        return
    if not C.STATION_CATCHMENT_CSV.exists():
        sys.exit("data/meta/station_catchment.csv 가 없습니다. 먼저 --auto 로 초안을 만드세요.")
    sc = pd.read_csv(C.STATION_CATCHMENT_CSV, encoding="utf-8-sig", dtype=str).dropna(subset=["catchment_codes"])
    sites = pd.read_csv(C.TMS_SITE_COORDS, encoding="utf-8-sig").dropna(subset=["lat", "lon"])
    sites["zone"] = [which(polys, r.lon, r.lat) for r in sites.itertuples()]
    print(f"[TMS] 좌표 {len(sites)}곳 중 구역 안 {sites['zone'].notna().sum()}곳")
    rows = []
    for _, r in sc.iterrows():
        codes = {c.strip() for c in r["catchment_codes"].split(";") if c.strip()}
        hit = sites[sites["zone"].isin(codes)]
        rows.append({"station": r["station"], "구역 수": len(codes), "사업장 수": len(hit), "upstream_tms": ";".join(hit["site"])})
    sug = pd.DataFrame(rows)
    path = C.META_DIR / "upstream_suggest.csv"
    sug.to_csv(path, index=False, encoding="utf-8-sig")
    print(sug.to_string(index=False), f"\n[저장] {path}")
    if a.apply:
        m = st.set_index("station")
        for _, r in sug.iterrows():
            if r["station"] in m.index and r["upstream_tms"]:
                m.loc[r["station"], "upstream_tms"] = r["upstream_tms"]
                m.loc[r["station"], "link_note"] = f"{m.loc[r['station'], 'link_note'] or ''}; upstream_tms 유역 경계 기반".strip("; ")
        schema.write(m.reset_index()[st.columns], "stations", mode="replace")
        print("stations.csv 반영 완료 → python run_all.py 42 43 44 45")


if __name__ == "__main__":
    main()
