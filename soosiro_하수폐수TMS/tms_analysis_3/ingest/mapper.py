# -*- coding: utf-8 -*-
"""
매핑 엔진 — '어떤 양식의 자료든' JSON 설명서(매핑) 하나로 표준 양식으로 바꾼다.

    python ingest/mapper.py ingest/mappings/kma_asos_daily.json            # 변환 후 표준 파일에 합치기
    python ingest/mapper.py ingest/mappings/xxx.json --dry-run             # 저장하지 않고 결과 미리보기
    python ingest/mapper.py ingest/mappings/xxx.json --mode replace        # 표준 파일 교체

새 자료가 생기면:
  1) python tools/peek.py <파일>            → 구조 출력(이것을 Claude 에게 붙여 넣기)
  2) python tools/make_mapping.py <파일> --target weather_daily  → 매핑 초안 자동 생성(열 이름 추정)
  3) 초안의 빈칸·추정값을 확인(또는 Claude 가 수정) → mapper.py 로 실행

매핑 JSON 키 (★ 필수)
 ★ target        : 표준 양식 이름(python -m core.schema 로 목록 확인)
 ★ inputs        : 파일 경로 glob 목록(프로젝트 폴더 기준). 예 ["data/inbox/kma/*.csv"]
   read          : {"encoding": "auto|utf-8-sig|cp949", "sheet": 0, "header_row": 0, "skiprows": [], "sep": ","}
   filename_regex: 파일명에서 값 뽑기. 예 "\\[(?P<basin>[^_]+)_(?P<station>[^\\]]+)\\]"
   columns       : {원본열: 표준열} 정확히 같은 이름
   columns_contains: {표준열: "원본열에 포함된 글자"} — 열 이름이 조금씩 다를 때(첫 번째 일치 열)
   pivot_long    : 긴 형태(항목명·값 두 열) → 넓게. {"index": ["station","datetime"], "item": "항목명", "value": "측정값",
                   "item_map": {"총인": "TP"}}
   constants     : {표준열: 고정값}  예 {"source": "ASOS"}
   derive        : {표준열: "파이썬 식"}  df·pd·np 사용 가능. 예 {"date": "pd.to_datetime(df['년'].astype(str)+'-'+df['월'].astype(str)+'-1')"}
   datetime      : {"col": "datetime", "format": "%Y%m%d%H%M", "combine": ["날짜","시각"]}   (선택)
   na_tokens     : 결측으로 볼 글자. 기본 ["", "-", "ND", "N.D", "불검출", "NA"]
   nd_value      : ND 를 숫자로 둘 때: "nan"(기본) | "half_min"(그 열 최솟값의 1/2)
   scale         : {표준열: 곱할 수}  예 {"TP": 0.001}  (μg/L → mg/L)
   fillna        : {표준열: 값}  예 {"rain_mm": 0}
   filters       : ["파이썬 조건식"]  예 ["df['basin'].isin(['한강','금강'])"]
   rename_values : {표준열: {원래값: 새값}}
   aggregate_daily: 시간자료를 일자료로 요약(river_daily 대상일 때): {"from": "datetime"}
   keep_extra    : true 면 매핑하지 않은 열도 남김(기본 false)
   drop          : 버릴 열 목록
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from core import schema  # noqa: E402

DEFAULT_NA = ["", "-", "--", "ND", "N.D", "N.D.", "불검출", "NA", "N/A", "nan", "NaN", "미측정"]


def read_any(path: Path, read: dict) -> pd.DataFrame:
    enc = read.get("encoding", "auto")
    hdr = read.get("header_row", 0)
    skip = read.get("skiprows")
    suf = path.suffix.lower()
    if suf in (".xlsx", ".xls", ".xlsm"):
        return pd.read_excel(path, sheet_name=read.get("sheet", 0), header=hdr, skiprows=skip, dtype=str)
    if suf == ".json":
        obj = json.loads(path.read_text(encoding="utf-8"))
        rec = obj
        for k in read.get("json_path", []):     # 예: ["response","body","items","item"]
            rec = rec[k]
        return pd.DataFrame(rec).astype(str)
    encs = [enc] if enc != "auto" else ["utf-8-sig", "cp949", "euc-kr", "utf-16"]
    last = None
    for e in encs:
        try:
            return pd.read_csv(path, encoding=e, header=hdr, skiprows=skip, sep=read.get("sep", ","),
                               dtype=str, low_memory=False, compression="infer")
        except (UnicodeDecodeError, UnicodeError) as ex:
            last = ex
    raise last


def apply_mapping(df: pd.DataFrame, m: dict, fname: str = "") -> pd.DataFrame:
    df = df.copy()
    df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]
    if m.get("filename_regex"):
        mm = re.search(m["filename_regex"], fname)
        if mm:
            for k, v in mm.groupdict().items():
                df[k] = v
    if m.get("pivot_long"):
        pl = m["pivot_long"]
        df[pl["item"]] = df[pl["item"]].map(lambda x: pl.get("item_map", {}).get(str(x).strip(), str(x).strip()))
        idx = [m.get("columns", {}).get(c, c) for c in pl["index"]]
        df = df.rename(columns=m.get("columns", {}))
        df = df.pivot_table(index=idx, columns=pl["item"], values=pl["value"], aggfunc="first").reset_index()
        df.columns.name = None
    out = pd.DataFrame(index=df.index)
    used = set()
    for src, dst in m.get("columns", {}).items():
        if src in df:
            out[dst] = df[src]
            used.add(src)
        elif dst in df:
            out[dst] = df[dst]
    for dst, pat in m.get("columns_contains", {}).items():
        if dst in out:
            continue
        cand = [c for c in df.columns if pat in c and c not in used]
        if cand:
            out[dst] = df[cand[0]]
            used.add(cand[0])
    for k in df.columns:   # filename_regex 등으로 만든 표준 열
        if k in schema.SCHEMAS[m["target"]]["columns"] and k not in out:
            out[k] = df[k]
    if m.get("keep_extra"):
        for c in df.columns:
            if c not in used and c not in out:
                out[c] = df[c]
    if m.get("datetime"):
        dtc = m["datetime"]
        col = dtc.get("col", "datetime")
        s = (df[dtc["combine"]].astype(str).agg(" ".join, axis=1) if dtc.get("combine") else out[col]).astype(str).str.strip()
        # 24시 표기(기상청·홍수통제소: 24:00 또는 YYYYMMDD24) → 다음날 00시
        is24 = s.str.contains(r"24:00$") | (s.str.fullmatch(r"\d{8}24") if dtc.get("ymdh") else False)
        s = s.str.replace(r"24:00$", "00:00", regex=True).str.replace(r"^(\d{8})24$", r"\g<1>00", regex=True)
        t = pd.to_datetime(s, format=dtc.get("format"), errors="coerce")
        out[col] = t + pd.to_timedelta(is24.astype(int), unit="D")
    na = set(m.get("na_tokens", DEFAULT_NA))
    tgt = schema.SCHEMAS[m["target"]]["columns"]
    numeric = [c for c in out.columns if tgt.get(c, ("float",))[0] in ("float", "int") and c not in ("datetime", "date")]
    for c in numeric:
        s = out[c].astype(str).str.strip().str.replace(",", "", regex=False)
        is_nd = s.str.upper().isin({x.upper() for x in na if x})
        lt = s.str.match(r"^<\s*[\d.]+$")      # '<0.005' 같은 검출한계 미만 표기
        v = pd.to_numeric(s.str.replace("<", "", regex=False), errors="coerce")
        if m.get("nd_value") == "half_min":
            v = v.where(~lt, v / 2)
            v = v.mask(is_nd, v[v > 0].min() / 2 if (v > 0).any() else np.nan)
        else:
            v = v.mask(lt)
        out[c] = v
    out = out.drop(columns=[c for c in m.get("drop", []) if c in out])
    for c, val in m.get("constants", {}).items():
        out[c] = val
    for c, expr in m.get("derive", {}).items():
        out[c] = eval(expr, {"df": df, "out": out, "pd": pd, "np": np})  # noqa: S307 (로컬 설정 파일 전용)
    for c, f in m.get("scale", {}).items():
        if c in out:
            out[c] = out[c] * f
    for c, mp in m.get("rename_values", {}).items():
        if c in out:
            out[c] = out[c].map(lambda x: mp.get(x, x))
    for c, val in m.get("fillna", {}).items():
        if c in out:
            out[c] = out[c].fillna(val)
    for cond in m.get("filters", []):
        out = out[eval(cond, {"df": out, "pd": pd, "np": np})]  # noqa: S307
    return out


def aggregate_daily(h: pd.DataFrame) -> pd.DataFrame:
    keys = ["basin", "station"]
    vals = [c for c in h.columns if c not in keys + ["datetime"] and pd.api.types.is_numeric_dtype(h[c])]
    h = h.assign(date=pd.to_datetime(h["datetime"]).dt.normalize())
    g = h.groupby(keys + ["date"])
    a = g[vals].agg(["mean", "min", "max", "median", "count"])
    a.columns = [f"{v}_{s.replace('median', 'med').replace('count', 'n')}" for v, s in a.columns]
    a.insert(0, "n_records", g.size())
    return a.reset_index()


def run_mapping(path, mode=None, dry_run=False):
    path = Path(path)
    m = json.loads(path.read_text(encoding="utf-8"))
    files = sorted({f for pat in m["inputs"] for f in glob.glob(str(BASE / pat), recursive=True)})
    if not files:
        print(f"[매핑 {path.name}] 입력 파일 없음: {m['inputs']}")
        return None
    parts = []
    for f in files:
        raw = read_any(Path(f), m.get("read", {}))
        parts.append(apply_mapping(raw, m, Path(f).name))
        print(f"  읽음 {Path(f).relative_to(BASE)}  {len(raw):,}행")
    df = pd.concat(parts, ignore_index=True, sort=False)
    if m.get("aggregate_daily"):
        df = aggregate_daily(df)
    df = schema.coerce(df, m["target"])
    issues = schema.validate(df, m["target"])
    print(f"[매핑 {path.name}] → {m['target']}  {len(df):,}행 · 열 {list(df.columns)[:12]}{'…' if df.shape[1] > 12 else ''}")
    if issues:
        print("  ⚠ 검사: " + " / ".join(issues))
    if dry_run:
        print(df.head(10).to_string())
        return df
    schema.write(df, m["target"], mode=mode or m.get("mode", "merge"))
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="매핑 JSON 으로 자료를 표준 양식으로 변환")
    ap.add_argument("mapping", nargs="+")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--mode", choices=["merge", "replace"])
    a = ap.parse_args()
    for mp in a.mapping:
        run_mapping(mp, a.mode, a.dry_run)
