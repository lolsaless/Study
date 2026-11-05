# -*- coding: utf-8 -*-
"""
WAMIS(국가수자원관리종합정보시스템) 유량 일자료 수집 — 한강 밖(낙동강·금강·영산강) 유량 보완용   (collectors/collect_wamis_flow.py)

API   http://www.wamis.go.kr:8080/wamis/openapi/wkw/flw_dtdata?obscd=<관측소>&year=<연도>&key=<키>&output=json
      (WAMIS > OpenAPI 메뉴에서 키 발급. 작업 경로·파라미터는 WAMIS OpenAPI 안내 페이지로 반드시 확인 — 코드는 --test 로 형식부터 본다)
관측소 data/meta/stations.csv 의 flow_obscd (WAMIS 관측소 코드는 홍수통제소 코드와 같은 7자리가 많다)
결과  data/raw/wamis/wamis_flow_daily.csv  (obscd, obs_name, date, flow_cms)
다음  python tools/make_mapping.py data/raw/wamis --target flow_daily --name wamis_flow → 확인 → 02번
※ 응답 형식이 다르면 --test 출력을 Claude 에게 주면 이 파일의 parse() 만 고치면 된다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import BASE, get_json, read_key  # noqa: E402

URL = "http://www.wamis.go.kr:8080/wamis/openapi/wkw/flw_dtdata"
OUT = BASE / "data" / "raw" / "wamis"


def parse(js, obscd):
    """WAMIS 응답 → 행 목록. 흔한 형태: {"result":{"code":"success"},"count":n,"list":[{"ymd":"20240101","fw":"12.3"}…]}"""
    lst = js.get("list") or js.get("content") or []
    rows = []
    for r in lst:
        ymd = r.get("ymd") or r.get("YMD") or r.get("ymdhm")
        q = r.get("fw") or r.get("flw") or r.get("FW")
        rows.append({"obscd": obscd, "date": str(ymd)[:8], "flow_cms": q})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key")
    ap.add_argument("--obscd", help="쉼표 구분(없으면 stations.csv 의 flow_obscd)")
    ap.add_argument("--years", default="2024,2025")
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    key = read_key("WAMIS_KEY", a.key)
    codes = a.obscd.split(",") if a.obscd else sorted(pd.read_csv(BASE / "data/meta/stations.csv", dtype=str)["flow_obscd"].dropna().unique())
    rows = []
    for c in codes[:1] if a.test else codes:
        for y in a.years.split(","):
            js, err = get_json(URL, {"obscd": c, "year": y, "key": key, "output": "json"})
            if a.test:
                print(str(js)[:2000] if js else err)
                return
            if js is None:
                print(f"{c} {y} 실패: {err}")
                continue
            rows += parse(js, c)
    d = pd.DataFrame(rows)
    d["date"] = pd.to_datetime(d["date"], format="%Y%m%d", errors="coerce").dt.strftime("%Y-%m-%d")
    OUT.mkdir(parents=True, exist_ok=True)
    d.to_csv(OUT / "wamis_flow_daily.csv", index=False, encoding="utf-8-sig")
    print(f"[저장] {OUT / 'wamis_flow_daily.csv'} ({len(d):,}행)")


if __name__ == "__main__":
    main()
