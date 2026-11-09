# -*- coding: utf-8 -*-
"""
02. 보조 자료(기상·유량·관측소 좌표 등) → 표준 양식   [준비 단계]

- ingest/mappings/*.json 중 "auto": true 인 매핑을 모두 실행한다(새 매핑을 만들어 auto 를 켜면 자동 포함).
- 일자료에 새 측정소가 생기면 data/meta/stations.csv 에 빈 행을 추가한다(연결 정보는 사람이 채움).
- 결과: data/standard/weather_daily.csv, flow_daily.csv, obs_stations.csv  + results/02_ingest_aux/summary.md

실행  python 02_ingest_aux.py                 (auto 매핑 전부, 표준 파일은 새로 만듦)
      python 02_ingest_aux.py kma_asos_daily  (이름에 글자가 들어간 매핑만, 기존 표준 파일에 합침)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "ingest"))

import pandas as pd

import config as C
from core import Report, schema
from mapper import run_mapping


def sync_stations(rep):
    if not schema.available("river_daily"):
        return
    d = schema.read("river_daily", usecols=["basin", "station"]).drop_duplicates()
    f = schema.SCHEMAS["stations"]["file"]
    if not f.exists():
        rep.p("data/meta/stations.csv 가 없어 목록만 새로 만들었다(연결 정보는 비어 있음).")
        new = d.assign(waterbody=d["station"].str.endswith("호").map({True: "호소", False: "하천"}))
        schema.write(new, "stations", mode="replace")
        return
    st = schema.read("stations")
    add = d[~d["station"].isin(st["station"])]
    if len(add):
        add = add.assign(waterbody=add["station"].str.endswith("호").map({True: "호소", False: "하천"}),
                         link_note="새 측정소 — 연결 정보 입력 필요")
        schema.write(add, "stations", mode="merge")
        rep.finding(f"새 측정소 {len(add)}곳을 data/meta/stations.csv 에 추가: {', '.join(add['station'])} (연결 정보 입력 필요)")
    filled = {c: int(st[c].notna().sum()) for c in ["lat", "weather_stn", "flow_obscd", "upstream_tms", "stem"]}
    rep.kv({f"stations.csv '{k}' 채워진 측정소": v for k, v in filled.items()})


def main():
    rep = Report("02_ingest_aux", "02. 보조 자료 표준화(기상·유량·관측소)", level="준비",
                 purpose="매핑 JSON 으로 보조 자료를 표준 양식으로 바꾸고, 측정소 연결표를 점검한다.")
    pick = sys.argv[1:]
    maps = sorted(C.MAPPINGS_DIR.glob("*.json"))
    rows, first = [], set()
    for mp in maps:
        m = json.loads(mp.read_text(encoding="utf-8"))
        if mp.name.startswith("_") or (pick and not any(k in mp.stem for k in pick)) or (not pick and not m.get("auto")):
            continue
        tgt = m["target"]
        mode = "merge" if pick or tgt in first else "replace"   # 전체 실행이면 대상별 첫 매핑에서 새로 만든다
        first.add(tgt)
        try:
            df = run_mapping(mp, mode=mode)
            rows.append({"매핑": mp.name, "대상": tgt, "행": 0 if df is None else len(df), "상태": "입력 없음" if df is None else "OK"})
        except Exception as e:  # noqa: BLE001
            rows.append({"매핑": mp.name, "대상": tgt, "행": 0, "상태": f"오류: {e}"})
    rep.h("1. 매핑 실행 결과")
    rep.table(pd.DataFrame(rows))
    rep.h("2. 표준 자료 현황")
    stat = []
    for n, s in schema.SCHEMAS.items():
        if s["file"].exists():
            k = s["keys"][0]
            df = schema.read(n, usecols=lambda c: c in s["keys"] + ["date"])
            stat.append({"양식": n, "파일": str(s["file"].relative_to(C.BASE_DIR)), "행": len(df),
                         "개체 수": df[k].nunique(),
                         "기간": f"{df['date'].min():%Y-%m-%d}~{df['date'].max():%Y-%m-%d}" if "date" in df else ""})
        else:
            stat.append({"양식": n, "파일": str(s["file"].relative_to(C.BASE_DIR)), "행": 0, "개체 수": 0, "기간": "없음"})
    rep.table(pd.DataFrame(stat))
    for r in stat:
        if r["행"]:
            rep.finding(f"{r['양식']}: {r['행']:,}행 · {r['개체 수']}개 지점/측정소 · {r['기간'] or '-'}")
    rep.h("3. 측정소 연결표(data/meta/stations.csv)")
    sync_stations(rep)
    rep.save()


if __name__ == "__main__":
    main()
