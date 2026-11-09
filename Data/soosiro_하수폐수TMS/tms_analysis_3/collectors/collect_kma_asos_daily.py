# -*- coding: utf-8 -*-
"""
기상청 ASOS 일자료(공공데이터포털 '기상청_지상(종관, ASOS) 일자료 조회서비스') 수집   (collectors/collect_kma_asos_daily.py)

API   http://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList
요청  serviceKey, pageNo, numOfRows(≤999), dataType=JSON, dataCd=ASOS, dateCd=DAY, startDt, endDt(YYYYMMDD, 전날까지), stnIds
응답  tm(날짜), stnId, stnNm, avgTa, minTa, maxTa, sumRn(일강수, 비 없으면 빈칸) …
지점  기본은 data/meta/stations.csv 의 weather_stn 에 적힌 지점 전부(4대강 측정소 연결 지점)

실행  python collectors/collect_kma_asos_daily.py --test                 (지점 1곳 1주일 → 형식 확인)
      python collectors/collect_kma_asos_daily.py --start 2024-01-01 --end 2025-12-31
      python collectors/collect_kma_asos_daily.py --stn 108,119
결과  data/raw/kma_asos/kma_asos_daily_datagokr.csv (기상자료개방포털 CSV 와 같은 한글 열 이름)
다음  python 02_ingest_aux.py   (매핑 kma_asos_daily.json 이 자동으로 읽음)
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import BASE, get_json, items_of, read_key  # noqa: E402

URL = "http://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"
OUT = BASE / "data" / "raw" / "kma_asos"


def fetch_year(key, stn, a, b):
    cache = OUT / "_cache" / f"{stn}_{a:%Y%m%d}_{b:%Y%m%d}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8")), ""
    js, err = get_json(URL, {"serviceKey": key, "pageNo": 1, "numOfRows": 999, "dataType": "JSON", "dataCd": "ASOS",
                             "dateCd": "DAY", "startDt": f"{a:%Y%m%d}", "endDt": f"{b:%Y%m%d}", "stnIds": stn})
    if js is None:
        return None, err
    it, msg = items_of(js)
    if msg and not it:
        return None, msg
    if b < pd.Timestamp.today().normalize() - pd.Timedelta(days=3):   # 끝난 기간만 캐시
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(it, ensure_ascii=False), encoding="utf-8")
    return it, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key")
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default=f"{pd.Timestamp.today() - pd.Timedelta(days=1):%Y-%m-%d}")
    ap.add_argument("--stn", help="쉼표로 구분한 지점번호(없으면 stations.csv 의 weather_stn 전부)")
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    key = read_key("DATA_GO_KR_KEY", a.key)
    if a.stn:
        stns = a.stn.split(",")
    else:
        st = pd.read_csv(BASE / "data" / "meta" / "stations.csv", dtype=str)
        stns = sorted(st["weather_stn"].dropna().unique())
    if a.test:
        stns, a.start, a.end = stns[:1], "2024-07-01", "2024-07-07"
    jobs = []
    for s in stns:
        for y0 in pd.date_range(pd.Timestamp(a.start).replace(month=1, day=1), a.end, freq="YS"):
            jobs.append((s, max(y0, pd.Timestamp(a.start)), min(y0 + pd.offsets.YearEnd(0), pd.Timestamp(a.end))))
    print(f"지점 {len(stns)}곳, 요청 {len(jobs)}건")
    rows, fails = [], []
    with ThreadPoolExecutor(4) as ex:
        futs = {ex.submit(fetch_year, key, *j): j for j in jobs}
        for f in as_completed(futs):
            it, err = f.result()
            (fails.append((futs[f], err)) if it is None else rows.extend(it))
    if fails:
        print(f"실패 {len(fails)}건 예: {fails[:2]}")
    d = pd.DataFrame(rows)
    if d.empty:
        sys.exit("자료 없음")
    if a.test:
        print(d.head().T.to_string())
        return
    out = pd.DataFrame({"지점": d["stnId"], "지점명": d["stnNm"], "일시": d["tm"],
                        "평균기온(°C)": pd.to_numeric(d["avgTa"], errors="coerce"),
                        "최저기온(°C)": pd.to_numeric(d["minTa"], errors="coerce"),
                        "최고기온(°C)": pd.to_numeric(d["maxTa"], errors="coerce"),
                        "일강수량(mm)": pd.to_numeric(d["sumRn"], errors="coerce")})
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "kma_asos_daily_datagokr.csv"
    out.drop_duplicates(["지점", "일시"]).sort_values(["지점", "일시"]).to_csv(path, index=False, encoding="utf-8-sig")
    print(f"[저장] {path} ({len(out):,}행)\n다음: python 02_ingest_aux.py")


if __name__ == "__main__":
    main()
