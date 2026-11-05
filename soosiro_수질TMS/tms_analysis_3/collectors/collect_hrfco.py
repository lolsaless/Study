# -*- coding: utf-8 -*-
"""
한강홍수통제소 Open API 수집 → 하천 수위·유량, 우량(강수)  (collectors/collect_hrfco.py, v2 에서 옮김)

※ 한강홍수통제소는 해외 클라우드에서의 접속을 끊는다(Claude 작업환경에서 연결 재설정 확인).
  반드시 국내 인터넷(사용자 PC)에서 실행하세요.

[하는 일]
1. 관측소 제원(info): 수위관측소·우량관측소 전체 → 위경도(도분초 → 십진수) 변환,
   범위(--region gyeonggi: 경기 주변 / all: 전국) 안 관측소를 고른다.
     data/raw/hrfco/hrfco_waterlevel_stations.csv, hrfco_rainfall_stations.csv
2. 우량 일자료(1D) → data/raw/hrfco/hrfco_rain_daily.csv   (지점 = 'HR'+코드)
3. 수위·유량 일자료(1D) → data/raw/hrfco/hrfco_waterlevel_daily.csv (wl_m 수위, flow_cms 유량)
4. (선택 --hourly) 시간자료(1H) → data/raw/hrfco/hrfco_rain_hourly.csv.gz, hrfco_waterlevel_hourly.csv.gz
받은 원문 JSON 은 data/raw/hrfco/_cache/ 에 캐시 → 다시 실행하면 없는 구간만 받는다.
받은 뒤: python 02_ingest_aux.py  (매핑 hrfco_*.json 이 표준 양식 flow_daily·weather_daily·obs_stations 로 변환)

[인증키] --key → 환경변수 HRFCO_KEY → data/api_keys.env 의 HRFCO_KEY=...   (저장소에 올리지 마세요)

실행: python collectors/collect_hrfco.py                        (2024-01-01 ~ 2026-06-30, 일자료)
      python collectors/collect_hrfco.py --hourly               (시간자료도)
      python collectors/collect_hrfco.py --only waterlevel      (수위·유량만)
      python collectors/collect_hrfco.py --test                 (관측소 1곳씩만 받아 형식 확인)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
OUT = DATA / "raw" / "hrfco"
RAW = OUT / "_cache"
API = "https://api.hrfco.go.kr/{key}/{hydro}/{kind}"
BBOX = (36.85, 38.35, 126.35, 127.95)     # 위도 최소·최대, 경도 최소·최대 (경기도 + 경계 여유). --region all 이면 전국
ID_COL = {"waterlevel": "wlobscd", "rainfall": "rfobscd"}


def read_key(cli):
    if cli:
        return cli
    if os.environ.get("HRFCO_KEY"):
        return os.environ["HRFCO_KEY"]
    f = DATA / "api_keys.env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("HRFCO_KEY="):
                return line.split("=", 1)[1].strip()
    sys.exit("한강홍수통제소 인증키가 없습니다. --key, 환경변수 HRFCO_KEY, 또는 data/api_keys.env 에 HRFCO_KEY=키 를 넣으세요.")


def get_json(url, retries=4):
    err = ""
    for k in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "tms-analysis/1.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8")), ""
        except Exception as e:  # noqa: BLE001
            err = str(e)
            time.sleep(2 * (k + 1))
    return None, err


def dms(v):
    """'127-05-31' / '127-5-31.5' / '127.0919' → 십진수"""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        return float(s)
    p = [float(x) for x in re.split(r"[-:\s°'\"]+", s) if x]
    if not p:
        return None
    return p[0] + (p[1] if len(p) > 1 else 0) / 60 + (p[2] if len(p) > 2 else 0) / 3600


def stations(key, hydro):
    url = API.format(key=key, hydro=hydro, kind="info.json")
    js, err = get_json(url)
    if js is None:
        sys.exit(f"{hydro} 관측소 제원 요청 실패: {err}\n(국내 인터넷인지, 인증키가 맞는지 확인)")
    d = pd.DataFrame(js.get("content", []))
    if d.empty:
        sys.exit(f"{hydro} 관측소 제원이 비어 있음: {str(js)[:300]}")
    d["lat_dd"] = d["lat"].map(dms)
    d["lon_dd"] = d["lon"].map(dms)
    la0, la1, lo0, lo1 = BBOX
    d["in_bbox"] = d["lat_dd"].between(la0, la1) & d["lon_dd"].between(lo0, lo1)
    out = OUT / f"hrfco_{hydro}_stations.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"{hydro}: 전체 {len(d)}곳, 범위 안 {int(d['in_bbox'].sum())}곳 → {out.relative_to(BASE)}")
    return d


def chunks(start, end, tt):
    """1D 는 1년, 1H 는 1개월 단위로 요청(응답이 잘리면 fetch 에서 다시 쪼갬)"""
    freq = "YS" if tt == "1D" else "MS"
    edges = list(pd.date_range(pd.Timestamp(start).to_period("M").start_time, end, freq=freq))
    if not edges or edges[0] > pd.Timestamp(start):
        edges = [pd.Timestamp(start)] + edges
    edges = [max(e, pd.Timestamp(start)) for e in edges] + [pd.Timestamp(end) + pd.Timedelta(days=1)]
    return [(a, b - pd.Timedelta(days=1)) for a, b in zip(edges[:-1], edges[1:]) if a < b]


def fmt(t, tt, end=False):
    if tt == "1D":
        return t.strftime("%Y%m%d")
    return (t + pd.Timedelta(hours=23) if end else t).strftime("%Y%m%d%H")


def fetch(key, hydro, tt, code, a, b, depth=0):
    cache = RAW / hydro / tt / f"{code}_{a:%Y%m%d}_{b:%Y%m%d}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8")), "cache"
    url = API.format(key=key, hydro=hydro, kind=f"list/{tt}/{code}/{fmt(a, tt)}/{fmt(b, tt, True)}.json")
    js, err = get_json(url)
    if js is None:
        return None, err
    rows = js.get("content", []) or []
    expect = (b - a).days + 1 if tt == "1D" else ((b - a).days + 1) * 24
    # 응답이 기대치의 절반도 안 되고 구간이 길면 반으로 나눠 다시(기간 제한 대응)
    if len(rows) < 0.5 * expect and (b - a).days > 31 and depth < 4:
        mid = a + (b - a) / 2
        mid = mid.normalize()
        r1, e1 = fetch(key, hydro, tt, code, a, mid, depth + 1)
        r2, e2 = fetch(key, hydro, tt, code, mid + pd.Timedelta(days=1), b, depth + 1)
        rows = (r1 or []) + (r2 or [])
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return rows, "ok"


def collect(key, hydro, tt, st, start, end, workers):
    idc = ID_COL[hydro]
    jobs = [(c, a, b) for c in st[idc].astype(str) for a, b in chunks(start, end, tt)]
    print(f"  {hydro} {tt}: 요청 {len(jobs)}건")
    rows, fails = [], []
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(fetch, key, hydro, tt, c, a, b): c for c, a, b in jobs}
        for i, f in enumerate(as_completed(futs), 1):
            r, e = f.result()
            if r is None:
                fails.append((futs[f], e))
            else:
                rows += r
            if i % 200 == 0:
                print(f"    {i}/{len(jobs)}")
    if fails:
        print(f"  실패 {len(fails)}건(다시 실행하면 이어받음). 예: {fails[:3]}")
    d = pd.DataFrame(rows)
    if d.empty:
        return d
    tcol = next(c for c in d.columns if c.lower().startswith("ymd"))
    d["time"] = pd.to_datetime(d[tcol].astype(str).str[:12 if tt != "1D" else 8],
                               format="%Y%m%d%H%M" if tt != "1D" else "%Y%m%d", errors="coerce")
    for c in ("wl", "fw", "rf"):
        if c in d:
            d[c] = pd.to_numeric(d[c].astype(str).str.strip().replace({"": None, "-": None}), errors="coerce")
    names = st.set_index(st[idc].astype(str))["obsnm"]
    d["obsnm"] = d[idc].astype(str).map(names)
    return d.drop_duplicates([idc, "time"]).sort_values([idc, "time"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key")
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2026-06-30")
    ap.add_argument("--only", choices=["waterlevel", "rainfall"])
    ap.add_argument("--hourly", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--test", action="store_true", help="관측소 1곳·1개월만 받아 응답 형식 확인")
    ap.add_argument("--region", choices=["gyeonggi", "all"], default="gyeonggi")
    a = ap.parse_args()
    key = read_key(a.key)
    hydros = [a.only] if a.only else ["waterlevel", "rainfall"]

    for hydro in hydros:
        st = stations(key, hydro)
        st = (st[st["in_bbox"]] if a.region == "gyeonggi" else st).copy()
        if a.test:
            st = st.head(1)
            a.end = (pd.Timestamp(a.start) + pd.Timedelta(days=30)).strftime("%Y-%m-%d")
        idc = ID_COL[hydro]
        for tt in (["1D", "1H"] if a.hourly else ["1D"]):
            d = collect(key, hydro, tt, st, a.start, a.end, a.workers)
            if d.empty:
                print(f"  {hydro} {tt}: 자료 없음")
                continue
            if a.test:
                print(d.head(10).to_string())
                continue
            if hydro == "rainfall" and tt == "1D":
                out = pd.DataFrame({"지점": "HR" + d[idc].astype(str), "지점명": d["obsnm"],
                                    "일시": d["time"].dt.strftime("%Y-%m-%d"), "일강수량(mm)": d["rf"]})
                path = OUT / "hrfco_rain_daily.csv"
            elif hydro == "rainfall":
                out = d[[idc, "obsnm", "time", "rf"]]
                path = OUT / "hrfco_rain_hourly.csv.gz"
            else:
                out = d[[idc, "obsnm", "time", "wl", "fw"]].rename(columns={"wl": "wl_m", "fw": "flow_cms"})
                path = OUT / f"hrfco_waterlevel_{'daily.csv' if tt == '1D' else 'hourly.csv.gz'}"
            path.parent.mkdir(parents=True, exist_ok=True)
            out.to_csv(path, index=False, encoding="utf-8-sig")
            print(f"  저장: {path.relative_to(BASE)} ({len(out):,}행, 관측소 {out.iloc[:, 0].nunique()}곳)")

    print("\n끝. 다음: python 02_ingest_aux.py → python run_all.py link")


if __name__ == "__main__":
    main()
