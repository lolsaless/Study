# -*- coding: utf-8 -*-
"""
01. 국가수질자동측정망 원자료 → 표준 양식(시간·일)   [준비 단계 · 가장 먼저 1회]

입력  data/raw/nier_auto_xlsx/**/[권역_측정소]시간자료(YYYYMMDD-YYYYMMDD).xlsx
       (물환경정보시스템 > 측정자료 조회 > 수질자동측정망 > 시간자료 '엑셀 다운로드' 그대로)
출력  data/standard/river_hourly.csv.gz   (1행 = 측정소×시각, git 제외 — 다시 만들 수 있음)
      data/standard/river_daily.csv.gz    (1행 = 측정소×일, 항목별 mean/min/max/med/n/nd)
      results/01_ingest_nier/              (파일 기록, 커버리지, ND 현황)

v2(merge_water_day.py) 대비 개선
- 증분 처리: 파일마다 변환 결과를 work/xlsx_cache/ 에 저장 → 새 연도 파일을 넣고 다시 돌리면 새 파일만 읽는다
- 측정소 이름 통일(config.STATION_ALIAS: 2025 '동북호' → '동복호'), 표준 열 이름(basin/station/date)
- 원자료가 없으면 기존 일별 CSV(data/raw/nier_auto_daily_v2)를 매핑(ingest/mappings/nier_daily_v2.json)으로 변환

실행  python 01_ingest_nier.py              (xlsx 우선, 없으면 기존 일별 CSV)
      python 01_ingest_nier.py --source daily_v2
      python 01_ingest_nier.py --rebuild    (캐시 무시하고 전부 다시 읽기)
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import config as C
from core import Report, schema

ND_TOKENS = {"ND", "N.D", "N.D.", "-", "--", "불검출", "미측정", "NA", "N/A"}
ND_DROP_RATIO = 0.5          # 한 파일에서 ND 비율이 이 이상인 항목 = 측정하지 않는 항목(VOC 등) → 제외
FILE_RE = re.compile(r"\[(?P<river>[^_\]]+)_(?P<station>[^\]]+)\].*?\((?P<s>\d{8})-(?P<e>\d{8})\)")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
CACHE = C.WORK_DIR / "xlsx_cache"
VAR_MAP = {"수온": "WT", "수소이온농도": "pH", "전기전도도": "EC", "용존산소": "DO", "탁도": "Turb",
           "총유기탄소": "TOC", "총질소": "TN", "총인": "TP", "클로로필-a": "Chl_a",
           "암모니아성질소": "NH3_N", "질산성질소": "NO3_N", "인산염인": "PO4_P",
           "카드뮴": "Cd", "납": "Pb", "구리": "Cu", "아연": "Zn", "페놀": "Phenol"}
STATS = {"mean": "mean", "min": "min", "max": "max", "median": "med", "count": "n"}


def nfc(x):
    return unicodedata.normalize("NFC", str(x))


def code_of(col):
    """'총인 (mg/L)' → TP,  '독성도(발광박테리아) (%)' → 독성도_발광박테리아"""
    col = nfc(col)
    m = re.search(r"\s*\(([^()]*)\)\s*$", col)
    base = col[:m.start()].strip() if m and not re.search(r"[가-힣]", m.group(1)) else col.strip()
    return VAR_MAP.get(base, re.sub(r"\W+", "_", base).strip("_"))


def read_xlsx(path: Path):
    """xlsx 1개 → (시간자료 DataFrame[basin, station, datetime, 항목…, 항목__nd…], 기록)"""
    m = FILE_RE.search(nfc(path.name))
    basin = m["river"] if m else nfc(path.parent.name)
    st_fn = m["station"] if m else nfc(path.stem)
    raw = pd.read_excel(path, header=None, dtype=str, engine="openpyxl")
    hdr = raw.index[raw.iloc[:, 0].astype(str).str.strip() == "측정일"]
    if not len(hdr):
        raise ValueError("'측정일' 머리글 행 없음")
    names = [nfc(re.sub(r"\s+", " ", str(x)).strip()) for x in raw.iloc[hdr[0]]]
    body = raw[raw.iloc[:, 0].astype(str).str.match(DATE_RE)].copy()
    body.columns = names
    dt = pd.to_datetime(body["측정일"].str.strip(), errors="coerce")
    body = body[dt.notna()]
    dt = dt[dt.notna()]
    st = body["측정소명"].map(lambda x: nfc(x).strip() if isinstance(x, str) else "") if "측정소명" in body else ""
    st = pd.Series(st, index=body.index).where(lambda s: s != "", st_fn)
    out = {"basin": basin, "station": st.map(lambda s: C.STATION_ALIAS.get(s, s)).values, "datetime": dt.values}
    log = {"file": nfc(path.name), "basin": basin, "station": C.STATION_ALIAS.get(st_fn, st_fn), "rows": len(body),
           "period": f"{dt.min():%Y-%m-%d}~{dt.max():%Y-%m-%d}" if len(dt) else "", "dropped_mostly_nd": "",
           "nd_items": "", "invalid_values": 0}
    dropped, nd_items, n_bad = [], [], 0
    for c in names:
        if c in ("측정일", "측정소명") or c == "nan":
            continue
        code = code_of(c)
        s = body[c].astype(str).str.strip().where(body[c].notna(), "")
        is_nd = s.str.upper().isin(ND_TOKENS) & (s != "")
        num = pd.to_numeric(s.str.replace(",", "", regex=False), errors="coerce")
        wq = code in C.CORE_VARS + C.EXTRA_VARS          # 독성지수 등은 음수가 정상일 수 있어 검사하지 않음
        bad = ((num < 0) & wq & (code != "WT")) | ((code == "WT") & (num < -5)) | ((code == "pH") & ((num < 0) | (num > 14)))
        n_bad += int(bad.sum())
        num = num.mask(bad)
        n_nd, n_any = int(is_nd.sum()), int((s != "").sum())
        if n_any and n_nd / n_any >= ND_DROP_RATIO:
            dropped.append(code)
            continue
        if n_nd:
            nd_items.append(f"{code}:{n_nd}")
            out[f"{code}__nd"] = is_nd.values.astype("int8")
        if code in out:   # 같은 코드로 겹치는 열은 빈 칸만 채움
            out[code] = pd.Series(out[code]).fillna(pd.Series(num.values)).values
        else:
            out[code] = num.values
    log.update(dropped_mostly_nd=", ".join(dropped), nd_items=", ".join(nd_items), invalid_values=n_bad)
    return pd.DataFrame(out), log


def _cached_read(path: Path):
    stt = path.stat()
    key = CACHE / f"{re.sub(r'[^0-9A-Za-z가-힣_]+', '_', nfc(path.stem))}__{stt.st_size}_{int(stt.st_mtime)}.pkl"
    if key.exists():
        try:
            return pd.read_pickle(key), True, None
        except Exception:  # noqa: BLE001
            pass
    try:
        res = read_xlsx(path)
    except Exception as e:  # noqa: BLE001
        return None, False, f"{path.name}: {e}"
    pd.to_pickle(res, key)
    return res, False, None


def to_daily(h: pd.DataFrame) -> pd.DataFrame:
    keys = ["basin", "station", "datetime"]
    vals = [c for c in h.columns if c not in keys and not c.endswith("__nd")]
    nds = [c for c in h.columns if c.endswith("__nd")]
    h = h.assign(date=h["datetime"].dt.normalize())
    g = h.groupby(["basin", "station", "date"], sort=True)
    agg = g[vals].agg(list(STATS))
    agg.columns = [f"{v}_{STATS[s]}" for v, s in agg.columns]
    agg = agg.round({c: 4 for c in agg.columns if not c.endswith("_n")})
    parts = [g.size().rename("n_records"), agg]
    if nds:
        nd = g[nds].sum().astype("int16")
        nd.columns = [c.replace("__nd", "_nd") for c in nd.columns]
        parts.append(nd)
    d = pd.concat(parts, axis=1).reset_index()
    order = ["basin", "station", "date", "n_records"]
    for v in vals:
        order += [f"{v}_{s}" for s in STATS.values()] + ([f"{v}_nd"] if f"{v}_nd" in d else [])
    d = d[order]
    nmask = [f"{v}_n" for v in vals]
    return d[(d[nmask] > 0).any(axis=1)].reset_index(drop=True)


def from_xlsx(rebuild=False):
    files = sorted(p for p in C.NIER_XLSX_DIR.rglob("*.xlsx") if not p.name.startswith(("~$", "._")))
    CACHE.mkdir(parents=True, exist_ok=True)
    if rebuild:
        for f in CACHE.glob("*.pkl"):
            f.unlink()
    print(f"[xlsx] {len(files)}개 파일")
    frames, logs, errors, n_cached = [], [], [], 0
    with ProcessPoolExecutor(max_workers=4) as ex:
        for i, (res, cached, err) in enumerate(ex.map(_cached_read, files), 1):
            if err:
                errors.append(err)
                continue
            df, lg = res
            frames.append(df)
            logs.append(lg)
            n_cached += cached
            if i % 20 == 0 or i == len(files):
                print(f"  {i}/{len(files)} (캐시 {n_cached})")
    h = pd.concat(frames, ignore_index=True, sort=False)
    n_dup = int(h.duplicated(["station", "datetime"]).sum())
    h = h.drop_duplicates(["station", "datetime"], keep="first")
    empty = [c for c in h.columns if c not in ("basin", "station", "datetime") and not c.endswith("__nd") and h[c].notna().sum() == 0]
    h = h.drop(columns=empty + [f"{c}__nd" for c in empty if f"{c}__nd" in h])
    h = h.sort_values(["basin", "station", "datetime"]).reset_index(drop=True)
    return h, pd.DataFrame(logs), errors, n_dup, n_cached


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["auto", "xlsx", "daily_v2"], default="auto")
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()
    rep = Report("01_ingest_nier", "01. 국가수질자동측정망 원자료 → 표준 양식", level="준비",
                 purpose="원자료(xlsx)를 표준 시간·일 자료로 바꾸고, 파일·측정소·항목별 자료 현황을 기록한다.")
    has_xlsx = any(C.NIER_XLSX_DIR.rglob("*.xlsx"))
    src = a.source if a.source != "auto" else ("xlsx" if has_xlsx else "daily_v2")

    if src == "daily_v2":
        sys.path.insert(0, str(C.BASE_DIR / "ingest"))
        from mapper import run_mapping
        run_mapping(C.MAPPINGS_DIR / "nier_daily_v2.json", mode="replace")
        d = schema.read("river_daily")
        rep.p("원자료 xlsx 가 없어 기존 일별 CSV(v2 변환본)를 매핑으로 표준화했다. 시간자료가 없으므로 22번의 시각 분석은 생략된다.")
        hourly = None
    else:
        hourly, logs, errors, n_dup, n_cached = from_xlsx(a.rebuild)
        hh = hourly.drop(columns=[c for c in hourly.columns if c.endswith("__nd")])
        schema.write(hh, "river_hourly", mode="replace")
        d = to_daily(hourly)
        schema.write(d, "river_daily", mode="replace")
        d = schema.read("river_daily")
        rep.kv({"읽은 파일": len(logs), "캐시 사용": n_cached, "읽기 실패": len(errors), "중복 시각 제거": n_dup,
                "시간자료 행": len(hourly), "물리적 불가능 값 제외(수질 항목 음수·pH 범위 밖)": int(logs["invalid_values"].sum())})
        if errors:
            rep.p("읽기 실패: " + "; ".join(errors))
        rep.csv(logs, "file_log.csv")
        nd = logs[logs["dropped_mostly_nd"] != ""]
        rep.p(f"ND 위주라 측정하지 않는 것으로 본 (파일·항목): {len(nd)}개 파일 — 주로 VOC·중금속(file_log.csv 참고)")
        bad_period = logs[~logs.apply(lambda r: r["period"][:4] in r["file"], axis=1)]
        if len(bad_period):
            rep.table(bad_period[["file", "period"]], "파일명 기간과 실제 기간이 다른 파일")

    rep.h("1. 수계별 자료 현황")
    vars_ = [v for v in C.CORE_VARS + C.EXTRA_VARS if f"{v}_n" in d]
    summ = d.groupby("basin").agg(측정소=("station", "nunique"), 일수=("date", "size"),
                                  시작=("date", "min"), 끝=("date", "max")).reset_index()
    rep.table(summ)
    rep.finding(f"표준 일자료: {d['basin'].nunique()}개 수계 · {d['station'].nunique()}개 측정소 · "
                f"{len(d):,}행 ({d['date'].min():%Y-%m-%d}~{d['date'].max():%Y-%m-%d})")

    rep.h("2. 측정소×항목 유효일 비율(달력일 기준, _n ≥ MIN_HOURS)")
    cal = d.groupby("station")["date"].agg(lambda s: (s.max() - s.min()).days + 1)
    cov = pd.DataFrame({v: d[d[f"{v}_n"] >= C.MIN_HOURS].groupby("station").size() for v in vars_}).reindex(cal.index)
    cov = (cov.div(cal, axis=0) * 100).round(1).fillna(0)
    cov.insert(0, "basin", d.groupby("station")["basin"].first())
    cov.insert(1, "달력일수", cal)
    rep.csv(cov.reset_index(), "coverage.csv")
    unmeasured = {v: int((cov[v] == 0).sum()) for v in vars_}
    rep.kv({f"{v} 미측정 측정소": n for v, n in unmeasured.items()})
    nd_cols = [c for c in d.columns if c.endswith("_nd")]
    if nd_cols:
        rep.h("3. 간헐적 ND(검출한계 미만 가능) 시간 비율")
        rows = []
        for c in nd_cols:
            v = c[:-3]
            tot = d[f"{v}_n"].sum() + d[c].sum()
            rows.append({"항목": v, "ND 시간": int(d[c].sum()), "ND 비율(%)": d[c].sum() / tot * 100 if tot else np.nan})
        t = pd.DataFrame(rows).sort_values("ND 비율(%)", ascending=False)
        rep.table(t)
        rep.p("ND 시간은 평균에서 빠지므로 저농도 항목(TP)의 일평균이 높게 나올 수 있다. 10번이 측정소별 ND 영향을 따로 본다.")
    rep.save()


if __name__ == "__main__":
    main()
