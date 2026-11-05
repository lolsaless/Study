# -*- coding: utf-8 -*-
"""
자료 불러오기 — 분석 스크립트는 이 함수들만 쓴다(표준 양식 → 분석용 형태).

load_daily()   : 일자료(긴 형태: basin, station, date, 항목...) — _n < MIN_HOURS 인 날은 결측 처리
load_hourly()  : 시간자료
load_stations(): 측정소 정보·연결표(data/meta/stations.csv)
load_weather() / load_flow() / load_tms(): 연계 자료(없으면 None)
wide(), series(): 시계열 형태 변환
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as C  # noqa: E402
from core import schema  # noqa: E402


def _cached(name: str, builder):
    """표준 CSV 를 읽어 work/ 에 pickle 캐시(원본이 바뀌면 자동 갱신, pandas 버전이 달라 못 읽어도 자동 재생성)"""
    src = schema.SCHEMAS[name]["file"]
    if not src.exists():
        raise FileNotFoundError(f"표준 자료 없음: {src.relative_to(C.BASE_DIR)} → 먼저 01_ingest_nier.py / 02_ingest_aux.py 실행")
    C.WORK_DIR.mkdir(exist_ok=True)
    cache = C.WORK_DIR / f"{name}_{int(src.stat().st_mtime)}_{src.stat().st_size}.pkl"
    if cache.exists():
        try:
            return pd.read_pickle(cache)
        except Exception:  # noqa: BLE001
            cache.unlink(missing_ok=True)
    for old in C.WORK_DIR.glob(f"{name}_*.pkl"):
        old.unlink(missing_ok=True)
    df = builder()
    df.to_pickle(cache)
    return df


def do_saturation(wt):
    """담수 용존산소 포화농도(mg/L), Benson & Krause(1984) 식 — 해수면 기압 가정"""
    T = np.asarray(wt, dtype=float) + 273.15
    ln = (-139.34411 + 1.575701e5 / T - 6.642308e7 / T ** 2 + 1.243800e10 / T ** 3 - 8.621949e11 / T ** 4)
    return np.exp(ln)


def load_daily(vars=None, min_hours=C.MIN_HOURS, minmax=False, basins=None, stations=None, quality=True):
    """일자료 → [basin, station, waterbody, date, year, month, doy, dow, <항목>(, <항목>_min/_max)]
    quality=True 면 10번이 '분석사용=False'로 판정한 측정소×항목은 결측 처리(work/usable_pairs.csv 가 있을 때)"""
    raw = _cached("river_daily", lambda: schema.read("river_daily"))
    allv = [c[:-5] for c in raw.columns if c.endswith("_mean")]
    vars = [v for v in (vars or allv) if f"{v}_mean" in raw]
    out = raw[["basin", "station", "date"]].copy()
    for v in vars:
        ok = raw[f"{v}_n"] >= min_hours if f"{v}_n" in raw else True
        out[v] = raw[f"{v}_mean"].where(ok)
        if minmax:
            out[f"{v}_min"] = raw[f"{v}_min"].where(ok)
            out[f"{v}_max"] = raw[f"{v}_max"].where(ok)
    qf = C.WORK_DIR / "usable_pairs.csv"
    if quality and qf.exists():
        q = pd.read_csv(qf, encoding="utf-8-sig")
        bad = q[~q["분석사용"].astype(bool)]
        for v, g in bad.groupby("var"):
            for suf in ["", "_min", "_max"]:
                if f"{v}{suf}" in out:
                    out.loc[out["station"].isin(g["station"]), f"{v}{suf}"] = np.nan
    if "WT" in out and "DO" in out:
        out["DO_sat"] = out["DO"] / do_saturation(out["WT"]) * 100
        if minmax:
            out["DO_sat_min"] = out["DO_min"] / do_saturation(out["WT"]) * 100
            out["DO_sat_max"] = out["DO_max"] / do_saturation(out["WT"]) * 100
    if basins:
        out = out[out["basin"].isin(basins)]
    if stations:
        out = out[out["station"].isin(stations)]
    st = load_stations()[["station", "waterbody"]]
    out = out.merge(st, on="station", how="left")
    d = out["date"]
    out["year"], out["month"], out["doy"], out["dow"] = d.dt.year, d.dt.month, d.dt.dayofyear, d.dt.dayofweek
    out["season"] = out["month"].map(season_of)
    return out.sort_values(["basin", "station", "date"]).reset_index(drop=True)


def load_hourly(basins=None):
    if not schema.available("river_hourly"):
        return None
    h = _cached("river_hourly", lambda: schema.read("river_hourly"))
    return h[h["basin"].isin(basins)] if basins else h


def load_stations():
    f = schema.SCHEMAS["stations"]["file"]
    if f.exists():
        st = schema.read("stations")
    else:  # 표가 없으면 일자료에서 목록만 만든다
        d = schema.read("river_daily", usecols=["basin", "station"]).drop_duplicates()
        st = d.assign(waterbody=np.where(d["station"].str.endswith("호"), "호소", "하천"))
    st["waterbody"] = st["waterbody"].fillna("하천")
    return st


def load_weather():
    return schema.read("weather_daily") if schema.available("weather_daily") else None


def load_flow():
    return schema.read("flow_daily") if schema.available("flow_daily") else None


def load_tms():
    """tms_analysis_2 의 방류수 TMS 정제자료(01_preprocess 산출물). 없으면 None"""
    if not C.TMS_CLEAN_PKL.exists():
        return None
    try:
        return pd.read_pickle(C.TMS_CLEAN_PKL)
    except Exception as e:  # noqa: BLE001
        print(f"[안내] TMS 자료를 읽지 못함({e}). tms_analysis_2 에서 01_preprocess.py 를 다시 실행하세요.")
        return None


def season_of(m):
    return {12: "겨울", 1: "겨울", 2: "겨울", 3: "봄", 4: "봄", 5: "봄",
            6: "여름", 7: "여름", 8: "여름", 9: "가을", 10: "가을", 11: "가을"}[int(m)]


def wide(df, v, stations=None):
    """행=날짜(연속), 열=측정소"""
    d = df if stations is None else df[df["station"].isin(stations)]
    w = d.pivot_table(index="date", columns="station", values=v, aggfunc="first").sort_index()
    return w.asfreq("D")


def series(df, station, v):
    s = df.loc[df["station"] == station].set_index("date")[v].sort_index()
    s = s[~s.index.duplicated()]
    return s.asfreq("D") if len(s) else s


def usable(df, vars, min_days=C.MIN_DAYS):
    """유효일수 ≥ min_days 인 (측정소, 항목) 표"""
    rows = []
    for (b, st), g in df.groupby(["basin", "station"]):
        for v in vars:
            if v in g:
                n = int(g[v].notna().sum())
                if n >= min_days:
                    rows.append({"basin": b, "station": st, "var": v, "n_days": n})
    return pd.DataFrame(rows, columns=["basin", "station", "var", "n_days"])


def holidays():
    return pd.to_datetime(pd.Series(C.HOLIDAYS)).dt.normalize()


def iter_series(df, vars, min_days=C.MIN_DAYS):
    """(basin, station, var, 연속 일 시계열) 를 차례로 돌려준다(유효일수 min_days 이상만)"""
    for (b, stn), g in df.groupby(["basin", "station"], sort=True):
        g = g.set_index("date").sort_index()
        g = g[~g.index.duplicated()].asfreq("D")
        for v in vars:
            if v in g and g[v].notna().sum() >= min_days:
                yield b, stn, v, g[v]


def tms_upstream_load(tms, sites, min_report=None):
    """상류 TMS 사업장들의 일 부하 합(kg/일)·방류수량 합(m³/일).
    보고한 사업장 비율이 min_report 이상인 날만 쓰고, 빠진 사업장 몫은 비례로 채운다(비율 추정).
    반환: index=date, [TOC_load, TN_load, TP_load, SS_load, Q, 보고비율]"""
    min_report = C.MIN_SITE_REPORT if min_report is None else min_report
    t = tms[tms["site"].isin(sites)]
    if t.empty:
        return None
    cols = [c for c in ["TOC_load", "TN_load", "TP_load", "SS_load", "Q"] if c in t]
    n_all = t["site"].nunique()
    g = t.groupby("date")
    frac = g["site"].nunique() / n_all
    out = g[cols].sum(min_count=1).div(frac, axis=0)
    out = out.where(frac >= min_report)
    out["보고비율"] = frac
    out.index = pd.to_datetime(out.index)
    return out.asfreq("D")


def flow_zone(q):
    """하천 유량 → 백분위 구간 이름(config.FLOW_ZONES)"""
    p = q.rank(pct=True)
    z = pd.Series(None, index=q.index, dtype=object)
    for lo, hi, name in C.FLOW_ZONES:
        z[(p >= lo) & (p < hi)] = name
    return z
