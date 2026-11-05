# -*- coding: utf-8 -*-
"""
표준 양식(스키마) 정의 · 검사 · 저장

모든 분석 스크립트는 data/standard/ 의 '표준 양식' 파일만 읽는다.
어떤 기관·형식의 자료든 이 양식으로만 바꿔 넣으면(ingest/mapper.py + 매핑 JSON) 분석 코드가 그대로 돈다.

    python -m core.schema            → 표준 양식 목록과 열 설명 출력
    python -m core.schema river_daily → 한 양식만 자세히
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as C  # noqa: E402

# 열 정의: 이름 → (자료형, 필수여부, 단위, 설명)
# 자료형: str / date / datetime / float / int
SCHEMAS = {
    "river_hourly": {
        "file": C.STD_DIR / "river_hourly.csv.gz",
        "keys": ["station", "datetime"],
        "desc": "하천·호소 수질 시간자료(1행 = 1측정소 × 1시각). 항목 열은 있는 것만 있으면 됨",
        "columns": {
            "basin": ("str", True, "-", "수계(한강·낙동강·금강·영산강 등)"),
            "station": ("str", True, "-", "측정소 이름(data/meta/stations.csv 와 같은 이름)"),
            "datetime": ("datetime", True, "-", "측정 시각 YYYY-MM-DD HH:MM"),
            **{v: ("float", False, C.VAR_INFO[v][1], C.VAR_INFO[v][0]) for v in C.CORE_VARS + C.EXTRA_VARS},
        },
        "allow_extra": True,      # 독성지수 등 다른 항목 열도 허용
    },
    "river_daily": {
        "file": C.STD_DIR / "river_daily.csv.gz",
        "keys": ["station", "date"],
        "desc": "하천·호소 수질 일자료. 항목마다 <코드>_mean/_min/_max/_med/_n(유효 시간수)[/_nd(ND 시간수)]",
        "columns": {
            "basin": ("str", True, "-", "수계"),
            "station": ("str", True, "-", "측정소"),
            "date": ("date", True, "-", "YYYY-MM-DD"),
            "n_records": ("int", False, "개", "그날 시간자료 행 수(정상 24)"),
            **{f"{v}_{s}": ("float", False, C.VAR_INFO[v][1], f"{C.VAR_INFO[v][0]} 일{s}")
               for v in C.CORE_VARS for s in ["mean", "min", "max", "med"]},
            **{f"{v}_n": ("int", False, "시간", f"{C.VAR_INFO[v][0]} 유효 시간수(0~24)") for v in C.CORE_VARS},
        },
        "allow_extra": True,
    },
    "weather_daily": {
        "file": C.STD_DIR / "weather_daily.csv",
        "keys": ["stn", "date"],
        "desc": "기상 일자료(기상청 ASOS·AWS, 홍수통제소 우량 등). 강수 빈칸=결측(0 아님)",
        "columns": {
            "stn": ("str", True, "-", "지점 번호(우량계는 'HR'+코드)"),
            "stn_name": ("str", False, "-", "지점명"),
            "date": ("date", True, "-", "YYYY-MM-DD"),
            "rain_mm": ("float", False, "mm", "일강수량"),
            "ta_mean": ("float", False, "℃", "일평균기온"),
            "ta_min": ("float", False, "℃", "일최저기온"),
            "ta_max": ("float", False, "℃", "일최고기온"),
            "source": ("str", False, "-", "출처(ASOS, AWS, HRFCO …)"),
        },
        "allow_extra": True,
    },
    "flow_daily": {
        "file": C.STD_DIR / "flow_daily.csv",
        "keys": ["obscd", "date"],
        "desc": "하천 수위·유량 일자료(한강홍수통제소·WAMIS 등)",
        "columns": {
            "obscd": ("str", True, "-", "관측소 코드"),
            "obs_name": ("str", False, "-", "관측소명"),
            "date": ("date", True, "-", "YYYY-MM-DD"),
            "wl_m": ("float", False, "m", "일평균 수위"),
            "flow_cms": ("float", False, "m³/s", "일평균 유량"),
            "source": ("str", False, "-", "출처"),
        },
        "allow_extra": True,
    },
    "obs_stations": {
        "file": C.STD_DIR / "obs_stations.csv",
        "keys": ["kind", "code"],
        "desc": "기상·수위·우량 관측소 좌표(측정소 연결·거리 계산용)",
        "columns": {
            "kind": ("str", True, "-", "weather / flow / rain"),
            "code": ("str", True, "-", "지점·관측소 코드(weather_daily.stn, flow_daily.obscd 와 같은 값)"),
            "name": ("str", False, "-", "이름"),
            "lat": ("float", False, "°", "위도(십진)"),
            "lon": ("float", False, "°", "경도(십진)"),
            "address": ("str", False, "-", "주소"),
            "source": ("str", False, "-", "출처"),
        },
        "allow_extra": True,
    },
    "stations": {
        "file": C.META_DIR / "stations.csv",
        "keys": ["station"],
        "desc": "수질 측정소 정보·연결표(사람이 고치는 표). 비어 있는 칸은 해당 연계분석에서 제외",
        "columns": {
            "basin": ("str", True, "-", "수계"),
            "station": ("str", True, "-", "측정소"),
            "waterbody": ("str", False, "-", "하천 / 호소(호소는 호소 기준으로 등급 판정)"),
            "stem": ("str", False, "-", "종단 분석용 줄기 이름(예: 남한강 본류)"),
            "stem_order": ("float", False, "-", "줄기 안 상류→하류 순서(1,2,3…)"),
            "lat": ("float", False, "°", "위도"),
            "lon": ("float", False, "°", "경도"),
            "target_grade": ("str", False, "-", "목표 등급(없으면 config.TARGET_GRADE)"),
            "weather_stn": ("str", False, "-", "연결할 기상 지점 번호(weather_daily.stn)"),
            "flow_obscd": ("str", False, "-", "연결할 수위·유량 관측소(flow_daily.obscd)"),
            "upstream_tms": ("str", False, "-", "상류 TMS 사업장(; 로 구분, tms_analysis_2 사업장명)"),
            "link_note": ("str", False, "-", "연결 근거·확인 여부"),
        },
        "allow_extra": True,
    },
}


def describe(name=None):
    names = [name] if name else list(SCHEMAS)
    out = []
    for n in names:
        s = SCHEMAS[n]
        out += [f"\n[{n}]  →  {s['file'].relative_to(C.BASE_DIR)}", f"  {s['desc']}", f"  키(중복 불가): {s['keys']}"]
        cols = s["columns"]
        shown = list(cols.items()) if name else list(cols.items())[:8]
        for c, (t, req, unit, d) in shown:
            out.append(f"   {'*' if req else ' '} {c:<14} {t:<9} {unit:<7} {d}")
        if not name and len(cols) > 8:
            out.append(f"     … 외 {len(cols) - 8}개 열 (python -m core.schema {n})")
    return "\n".join(out)


def coerce(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """스키마 자료형으로 변환(문자열 정리, 날짜 파싱, 숫자 변환)"""
    s = SCHEMAS[name]
    df = df.copy()
    for c, (t, *_r) in s["columns"].items():
        if c not in df:
            continue
        if t == "str":
            df[c] = df[c].astype("string").str.strip().astype(object).where(df[c].notna(), None)
        elif t == "date":
            df[c] = pd.to_datetime(df[c], errors="coerce").dt.normalize()
        elif t == "datetime":
            df[c] = pd.to_datetime(df[c], errors="coerce")
        elif t in ("float", "int"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def validate(df: pd.DataFrame, name: str) -> list[str]:
    """문제 목록(빈 리스트면 통과)"""
    s = SCHEMAS[name]
    issues = []
    for c, (t, req, *_r) in s["columns"].items():
        if req and c not in df:
            issues.append(f"필수 열 없음: {c}")
        elif req and df[c].isna().any():
            issues.append(f"필수 열 {c} 에 빈 값 {int(df[c].isna().sum())}개")
    if all(k in df for k in s["keys"]):
        dup = int(df.duplicated(s["keys"]).sum())
        if dup:
            issues.append(f"키 {s['keys']} 중복 {dup}행")
    known = set(s["columns"])
    if not s.get("allow_extra"):
        extra = [c for c in df.columns if c not in known]
        if extra:
            issues.append(f"모르는 열: {extra}")
    for c, (t, *_r) in s["columns"].items():
        if c in df and t in ("float", "int") and df[c].dtype == object:
            issues.append(f"{c} 가 숫자가 아님")
    return issues


def read(name: str, **kw) -> pd.DataFrame:
    s = SCHEMAS[name]
    f = s["file"]
    if not f.exists():
        raise FileNotFoundError(f"표준 자료 없음: {f}  (작업안내서.md 3장 참고)")
    dtype = {c: str for c, (t, *_r) in s["columns"].items() if t == "str"}
    df = pd.read_csv(f, encoding="utf-8-sig", dtype=dtype, low_memory=False, **kw)
    return coerce(df, name)


def available(name: str) -> bool:
    return SCHEMAS[name]["file"].exists()


def write(df: pd.DataFrame, name: str, mode: str = "merge") -> Path:
    """표준 파일 저장. mode='merge' → 기존 파일과 합치고 키가 같으면 새 값으로 덮어씀, 'replace' → 교체"""
    s = SCHEMAS[name]
    f = s["file"]
    f.parent.mkdir(parents=True, exist_ok=True)
    df = coerce(df, name)
    if mode == "merge" and f.exists():
        old = read(name)
        df = pd.concat([old, df], ignore_index=True, sort=False)
        df = df.drop_duplicates(s["keys"], keep="last")
    df = df.sort_values([k for k in s["keys"] if k in df]).reset_index(drop=True)
    issues = validate(df, name)
    for t in [c for c, (tt, *_r) in s["columns"].items() if tt == "date" and c in df]:
        df[t] = df[t].dt.strftime("%Y-%m-%d")
    df.to_csv(f, index=False, encoding="utf-8-sig")
    msg = f"[저장] {f.relative_to(C.BASE_DIR)}  {len(df):,}행"
    print(msg + ("" if not issues else "  ⚠ " + " / ".join(issues)))
    return f


if __name__ == "__main__":
    print(describe(sys.argv[1] if len(sys.argv) > 1 else None))
