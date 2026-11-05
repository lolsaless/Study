# -*- coding: utf-8 -*-
"""
국립환경과학원 수질자동측정망 Open API(공공데이터포털) 수집 → 시간자료 CSV   (collectors/collect_nier_api.py)

API   http://apis.data.go.kr/1480523/WaterQualityService/getRealTimeWaterQualityList
      (공공데이터포털 '국립환경과학원_수질 DB' / 데이터번호 15081073 → 활용신청 → '일반 인증키(Decoding)')
요청  serviceKey, resultType=json, numOfRows, pageNo, siteId(S0xxxx), startDate, endDate
응답  MSR_DATE(측정일시), SITE_ID, SITE_NAME, M?? (항목 코드)  — 항목 코드표는 ITEM_CODES(아래). 처음엔 --test 로 반드시 확인
주의  공개 주기: 확정자료는 보통 월 1회·수개월 지연. 최신 실시간 값은 물환경정보시스템 화면과 다를 수 있다.
      대량(수년치)은 물환경정보시스템 '시간자료 엑셀 다운로드'가 더 빠르고 확실하다(→ data/raw/nier_auto_xlsx 에 넣고 01번).

실행
  python collectors/collect_nier_api.py --test --site S01023            응답 형식·항목 코드 확인(1일치)
  python collectors/collect_nier_api.py --probe                         측정소 ID 탐색(S01001~S04040) → data/meta/nier_site_ids.csv
  python collectors/collect_nier_api.py --start 2026-01-01 --end 2026-06-30   (nier_site_ids.csv 의 모든 측정소)
결과  data/raw/nier_api/nier_api_hourly.csv  (+ 원문 캐시 data/raw/nier_api/_cache/)
다음  python ingest/mapper.py ingest/mappings/nier_api_hourly.json   → river_daily 에 합쳐짐(시간→일 요약)
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

URL = "http://apis.data.go.kr/1480523/WaterQualityService/getRealTimeWaterQualityList"
OUT = BASE / "data" / "raw" / "nier_api"
SITE_IDS = BASE / "data" / "meta" / "nier_site_ids.csv"
# 응답 항목 코드 → 표준 코드 (공개 예제 기준 추정. --test 출력과 반드시 대조해서 고칠 것)
ITEM_CODES = {
    "WT": ["M02", "M38", "M69"], "pH": ["M03", "M39", "M70"], "EC": ["M04", "M40", "M71"],
    "DO": ["M05", "M41", "M72"], "TOC": ["M06", "M81"], "Turb": ["M79", "M80", "M73"],
    "TN": ["M27"], "TP": ["M28"], "Chl_a": ["M29"],
}
BASIN_CODE = {"01": "한강", "02": "낙동강", "03": "금강", "04": "영산강"}


def fetch(key, site, start, end, page=1, rows=1000):
    cache = OUT / "_cache" / f"{site}_{start:%Y%m%d}_{end:%Y%m%d}_{page}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8")), ""
    js, err = get_json(URL, {"serviceKey": key, "resultType": "json", "numOfRows": rows, "pageNo": page,
                             "siteId": site, "startDate": f"{start:%Y%m%d}000000", "endDate": f"{end:%Y%m%d}235959"})
    if js is None:
        return None, err
    it, msg = items_of(js)
    if msg and not it:
        return None, msg
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(it, ensure_ascii=False), encoding="utf-8")
    return it, ""


def fetch_range(key, site, start, end):
    """한 달씩, 응답이 꽉 차면 다음 쪽까지"""
    out = []
    for a in pd.date_range(start, end, freq="MS").union([pd.Timestamp(start)]):
        b = min(a + pd.offsets.MonthEnd(0), pd.Timestamp(end))
        page = 1
        while True:
            it, err = fetch(key, site, a, b, page)
            if it is None:
                print(f"  {site} {a:%Y-%m} 실패: {err}")
                break
            out += it
            if len(it) < 1000:
                break
            page += 1
    return out


def flatten(items):
    d = pd.DataFrame(items)
    if d.empty:
        return d
    d.columns = [c.upper() for c in d.columns]
    res = pd.DataFrame({"site_id": d.get("SITE_ID"), "station": d.get("SITE_NAME"),
                        "datetime": d.get("MSR_DATE")})
    for std, codes in ITEM_CODES.items():
        for c in codes:
            if c in d:
                v = pd.to_numeric(d[c], errors="coerce")
                res[std] = res[std].fillna(v) if std in res else v
    res["basin"] = res["site_id"].astype(str).str[1:3].map(BASIN_CODE)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key")
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default=f"{pd.Timestamp.today():%Y-%m-%d}")
    ap.add_argument("--site", help="측정소 ID 하나만(예: S01023)")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--probe", action="store_true", help="측정소 ID 탐색")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    key = read_key("DATA_GO_KR_KEY", a.key)

    if a.test:
        site = a.site or "S01023"
        day = pd.Timestamp(a.start)
        js, err = get_json(URL, {"serviceKey": key, "resultType": "json", "numOfRows": 5, "pageNo": 1, "siteId": site,
                                 "startDate": f"{day:%Y%m%d}000000", "endDate": f"{day:%Y%m%d}235959"})
        print("원문(앞부분):", json.dumps(js, ensure_ascii=False)[:1500] if js else err)
        it, msg = items_of(js)
        print(f"\nitem {len(it)}개, 메시지: {msg or '정상'}")
        if it:
            print("열 이름:", list(it[0].keys()))
            print("→ ITEM_CODES 와 대조하세요. 다르면 이 파일 ITEM_CODES 를 고치거나 출력을 Claude 에게 주세요.")
        return

    if a.probe:
        rows = []
        cands = [f"S{b}{n:03d}" for b in BASIN_CODE for n in range(1, 41)]
        day = pd.Timestamp(a.start)

        def one(s):
            js, _ = get_json(URL, {"serviceKey": key, "resultType": "json", "numOfRows": 1, "pageNo": 1, "siteId": s,
                                   "startDate": f"{day:%Y%m%d}000000", "endDate": f"{day:%Y%m%d}235959"})
            it, _ = items_of(js)
            return s, (it[0].get("SITE_NAME") or it[0].get("siteName")) if it else None
        with ThreadPoolExecutor(a.workers) as ex:
            for f in as_completed([ex.submit(one, s) for s in cands]):
                s, name = f.result()
                if name:
                    rows.append({"site_id": s, "basin": BASIN_CODE[s[1:3]], "station": name})
        t = pd.DataFrame(rows).sort_values("site_id")
        SITE_IDS.parent.mkdir(parents=True, exist_ok=True)
        t.to_csv(SITE_IDS, index=False, encoding="utf-8-sig")
        print(t.to_string(index=False), f"\n[저장] {SITE_IDS}")
        return

    if a.site:
        sites = [a.site]
    elif SITE_IDS.exists():
        sites = pd.read_csv(SITE_IDS, dtype=str)["site_id"].tolist()
    else:
        sys.exit("측정소 ID 목록이 없습니다. 먼저 --probe 를 실행하거나 --site 를 주세요.")
    allrows = []
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(fetch_range, key, s, a.start, a.end): s for s in sites}
        for f in as_completed(futs):
            allrows += f.result()
            print(f"  {futs[f]} 완료")
    d = flatten(allrows)
    if d.empty:
        sys.exit("받은 자료가 없습니다(--test 로 응답 확인).")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "nier_api_hourly.csv"
    if path.exists():
        d = pd.concat([pd.read_csv(path, dtype={"site_id": str}), d]).drop_duplicates(["site_id", "datetime"], keep="last")
    d.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"[저장] {path} ({len(d):,}행)\n다음: python ingest/mapper.py ingest/mappings/nier_api_hourly.json")


if __name__ == "__main__":
    main()
