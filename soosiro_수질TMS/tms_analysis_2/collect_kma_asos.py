# -*- coding: utf-8 -*-
"""
기상청 API허브 ASOS 시간자료(kma_sfctm3) 수집 → 시간·일 자료 + 지점정보  (collect_kma_asos.py)

[하는 일]
1. 경기도와 인접 ASOS 지점(STATIONS)의 시간자료를 월 단위로 받는다(API 1회 최대 31일).
   받은 원문은 data/weather_raw/kma_asos/<지점>_<YYYYMM>.txt 로 저장해 두고, 다시 실행하면 없는 달만 받는다.
2. 시간자료 → data/weather_hourly/kma_asos_hourly.csv.gz  (강우 이벤트 분석용: 시간 강수·기온)
3. 일자료   → data/weather/kma_asos_daily.csv           (21번이 읽는 기상청 일자료 양식)
   - 하루 = 01시~24시(기상청 일 통계 기준). 일강수량 = 그날 RN_DAY(누적 일강수량)의 최댓값
   - 평균기온 = 24개 정시 기온 평균(20개 이상일 때), 최저·최고 = 정시 기온의 최솟값·최댓값
     (기상청 공식 일 최저·최고는 분 자료 기준이라 0.1~1 ℃ 다를 수 있음)
4. 지점정보 → data/weather_stations.csv 에 ASOS 지점 좌표를 넣는다(다른 지점 행은 유지).

[인증키] 아래 순서로 찾는다(저장소에 키를 올리지 마세요).
  --key 인자 → 환경변수 KMA_AUTH_KEY → data/api_keys.env 의 KMA_AUTH_KEY=...
  * 이 스크립트는 API허브 'ASOS 시간자료(kma_sfctm3)' 활용신청만으로 동작한다.

실행: python collect_kma_asos.py                       (기본 2024-01 ~ 2026-06)
      python collect_kma_asos.py --start 2024-01 --end 2026-09
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
RAW_DIR = DATA / "weather_raw" / "kma_asos"
HOURLY_OUT = DATA / "weather_hourly" / "kma_asos_hourly.csv.gz"
DAILY_OUT = DATA / "weather" / "kma_asos_daily.csv"
STN_OUT = DATA / "weather_stations.csv"
URL = "https://apihub.kma.go.kr/api/typ01/url/kma_sfctm3.php?tm1={tm1}&tm2={tm2}&stn={stn}&help=0&authKey={key}"

# 경기도 + 인접 ASOS 지점. 위경도는 기상청 지점정보 기준 근삿값(소수 4자리).
# 지점정보 API(stn_inf) 활용신청 후 공식 값으로 바꾸면 더 정확하다.
STATIONS = {
    95: ("철원", 38.1479, 127.3042, "강원특별자치도 철원군"),
    98: ("동두천", 37.9019, 127.0607, "경기도 동두천시"),
    99: ("파주", 37.8859, 126.7665, "경기도 파주시"),
    101: ("춘천", 37.9026, 127.7357, "강원특별자치도 춘천시"),
    108: ("서울", 37.5714, 126.9658, "서울특별시 종로구"),
    112: ("인천", 37.4777, 126.6249, "인천광역시 중구"),
    114: ("원주", 37.3375, 127.9466, "강원특별자치도 원주시"),
    119: ("수원", 37.2723, 126.9853, "경기도 수원시 권선구"),
    127: ("충주", 36.9705, 127.9525, "충청북도 충주시"),
    131: ("청주", 36.6392, 127.4407, "충청북도 청주시"),
    201: ("강화", 37.7074, 126.4463, "인천광역시 강화군"),
    202: ("양평", 37.4886, 127.4945, "경기도 양평군"),
    203: ("이천", 37.2640, 127.4842, "경기도 이천시"),
    212: ("홍천", 37.6836, 127.8804, "강원특별자치도 홍천군"),
    232: ("천안", 36.7624, 127.2927, "충청남도 천안시"),
}
# 시간자료 열(앞 17개만 사용: 뒤쪽 문자열 열은 공백이 섞일 수 있어 쓰지 않는다)
COLS = ["TM", "STN", "WD", "WS", "GST_WD", "GST_WS", "GST_TM", "PA", "PS", "PT", "PR",
        "TA", "TD", "HM", "PV", "RN", "RN_DAY"]


def read_key(cli):
    if cli:
        return cli
    if os.environ.get("KMA_AUTH_KEY"):
        return os.environ["KMA_AUTH_KEY"]
    f = DATA / "api_keys.env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("KMA_AUTH_KEY="):
                return line.split("=", 1)[1].strip()
    sys.exit("기상청 인증키가 없습니다. --key, 환경변수 KMA_AUTH_KEY, 또는 data/api_keys.env 에 KMA_AUTH_KEY=키 를 넣으세요.")


def months(start, end):
    return pd.period_range(start, end, freq="M")


def fetch(stn, per, key, retries=4):
    out = RAW_DIR / f"{stn}_{per.strftime('%Y%m')}.txt"
    if out.exists() and out.stat().st_size > 0 and "#7777END" in out.read_text(encoding="cp949", errors="ignore"):
        return out, "cache"
    t1 = (per.start_time + pd.Timedelta(hours=1)).strftime("%Y%m%d%H%M")      # 그달 1일 01시
    t2 = (per.end_time.normalize() + pd.Timedelta(days=1)).strftime("%Y%m%d%H%M")  # 다음달 1일 00시(=말일 24시)
    url = URL.format(tm1=t1, tm2=t2, stn=stn, key=key)
    err = ""
    for k in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                b = r.read()
            txt = b.decode("cp949", errors="ignore")
            if "#7777END" in txt:
                out.write_bytes(b)
                return out, "ok"
            err = txt[:200].replace("\n", " ")
        except Exception as e:  # noqa: BLE001
            err = str(e)
        time.sleep(2 * (k + 1))
    return None, err


def parse(path):
    rows = []
    for line in path.read_text(encoding="cp949", errors="ignore").splitlines():
        if not line or line.startswith("#"):
            continue
        p = line.split()
        if len(p) < len(COLS):
            continue
        rows.append(p[:len(COLS)])
    d = pd.DataFrame(rows, columns=COLS)
    d["TM"] = pd.to_datetime(d["TM"], format="%Y%m%d%H%M", errors="coerce")
    for c in COLS[1:]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.replace({-9: np.nan, -9.0: np.nan, -99: np.nan, -99.0: np.nan})
    return d


def to_daily(h):
    h = h.copy()
    h["date"] = (h["TM"] - pd.Timedelta(hours=1)).dt.normalize()      # 01~24시 → 그날
    g = h.groupby(["STN", "date"])
    d = pd.DataFrame({
        "rain": g["RN_DAY"].max(),
        "rain_hsum": g["RN"].sum(min_count=1),
        "ta_n": g["TA"].count(),
        "ta_mean": g["TA"].mean(),
        "ta_min": g["TA"].min(),
        "ta_max": g["TA"].max(),
        "hm_mean": g["HM"].mean(),
    }).reset_index()
    d.loc[d["ta_n"] < 20, "ta_mean"] = np.nan
    # 일강수 누적값이 없으면 시간 강수 합으로 보완(4~10월은 1시간, 11~3월은 3시간 강수)
    d["rain"] = d["rain"].fillna(d["rain_hsum"])
    # 비가 안 온 날은 강수가 -9(자료없음)로 나온다 → 그날 관측(기온 20시간 이상)이 정상이면 0 mm
    d.loc[d["rain"].isna() & (d["ta_n"] >= 20), "rain"] = 0.0
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key")
    ap.add_argument("--start", default="2024-01")
    ap.add_argument("--end", default="2026-06")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    key = read_key(a.key)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    jobs = [(s, p) for s in STATIONS for p in months(a.start, a.end)]
    print(f"요청 {len(jobs)}건 (지점 {len(STATIONS)} × {len(months(a.start, a.end))}개월)")
    fails = []
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(fetch, s, p, key): (s, p) for s, p in jobs}
        for i, f in enumerate(as_completed(futs), 1):
            path, st = f.result()
            if path is None:
                fails.append((*futs[f], st))
            if i % 50 == 0:
                print(f"  {i}/{len(jobs)}")
    if fails:
        print(f"실패 {len(fails)}건(다시 실행하면 이어받음):")
        for s, p, e in fails[:10]:
            print(f"  {s} {p}: {e}")

    files = sorted(RAW_DIR.glob("*.txt"))
    h = pd.concat([parse(f) for f in files], ignore_index=True)
    lo = pd.Period(a.start, "M").start_time
    hi = pd.Period(a.end, "M").end_time.normalize() + pd.Timedelta(days=1)
    h = h[(h["TM"] > lo) & (h["TM"] <= hi)].drop_duplicates(["STN", "TM"]).sort_values(["STN", "TM"])
    HOURLY_OUT.parent.mkdir(parents=True, exist_ok=True)
    h[["TM", "STN", "TA", "TD", "HM", "WS", "RN", "RN_DAY", "PA"]].to_csv(HOURLY_OUT, index=False, encoding="utf-8-sig")

    d = to_daily(h)
    names = {k: v[0] for k, v in STATIONS.items()}
    daily = pd.DataFrame({"지점": d["STN"].astype(int), "지점명": d["STN"].map(names),
                          "일시": d["date"].dt.strftime("%Y-%m-%d"),
                          "평균기온(°C)": d["ta_mean"].round(1), "최저기온(°C)": d["ta_min"],
                          "최고기온(°C)": d["ta_max"], "일강수량(mm)": d["rain"],
                          "평균상대습도(%)": d["hm_mean"].round(1), "기온관측수": d["ta_n"]})
    DAILY_OUT.parent.mkdir(parents=True, exist_ok=True)
    daily.to_csv(DAILY_OUT, index=False, encoding="utf-8-sig")

    st = pd.DataFrame([{"지점": k, "지점명": v[0], "위도": v[1], "경도": v[2], "지점주소": v[3], "구분": "ASOS"}
                       for k, v in STATIONS.items()])
    if STN_OUT.exists():
        old = pd.read_csv(STN_OUT, encoding="utf-8-sig", dtype={"지점": str})
        old = old[~old["지점"].astype(str).isin(st["지점"].astype(str))]
        st = pd.concat([st.astype({"지점": str}), old], ignore_index=True)
    st.to_csv(STN_OUT, index=False, encoding="utf-8-sig")

    cov = daily.groupby("지점명").agg(일수=("일시", "size"), 강수결측=("일강수량(mm)", lambda x: x.isna().sum()),
                                     기온결측=("평균기온(°C)", lambda x: x.isna().sum()), 연강수_평균=("일강수량(mm)", "sum"))
    cov["연강수_평균"] = (cov["연강수_평균"] / (cov["일수"] / 365.25)).round(0)
    print(f"\n저장: {HOURLY_OUT.relative_to(BASE)} ({len(h):,}행), {DAILY_OUT.relative_to(BASE)} ({len(daily):,}행), {STN_OUT.relative_to(BASE)}")
    print(cov.to_string())


if __name__ == "__main__":
    main()
