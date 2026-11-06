"""soosiro 수질TMS 수집 파일 통합 코드 (수집 없이 병합·정제만)

data/raw/<연도Q분기>/<사업장>.csv  →  data/tms_all_raw.csv, data/tms_all_clean.csv

- 크롬/셀레니움이 필요 없습니다(pandas 만 필요). 어느 기기에서든 실행 가능.
- 이 파일이 있는 폴더의 data/ 를 기본으로 사용합니다. 다른 위치는 --data-dir 로 지정.
- 일부 파일이 깨져 있어도 건너뛰고 계속 진행하며, 결과 파일이 엑셀로 열려 있으면
  시각을 붙인 다른 이름으로 저장합니다.

사용:
    python soosiro_merge.py
    python soosiro_merge.py --data-dir "/경로/data"
    python soosiro_merge.py --keep-duplicates      # 같은 사업장·일자·방류구 중복 행 유지
"""
import argparse
import os
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd

COLS = [
    "순번", "연도", "분기", "사업장명", "일자", "방류구",
    "pH_측정값",
    "TOC_측정값", "TOC_배출량",
    "SS_측정값", "SS_배출량",
    "TN_측정값", "TN_배출량",
    "TP_측정값", "TP_배출량",
]
VALUE_COLS = COLS[6:]
KEY_COLS = ["연도", "일자", "사업장명", "방류구"]


def say(msg):
    print(msg, flush=True)


def fix_console_encoding():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors="replace")
        except Exception:
            pass


def read_csv_auto(path):
    last = None
    for enc in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(path, dtype=str, encoding=enc)
        except Exception as e:  # 인코딩·파싱 오류 → 다음 인코딩 시도
            last = e
    raise last


def save_csv_atomic(df, path):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    try:
        os.replace(tmp, path)
        return path
    except PermissionError:
        alt = path.with_name(f"{path.stem}_{datetime.now():%Y%m%d_%H%M%S}{path.suffix}")
        os.replace(tmp, alt)
        say(f"  [!] {path.name} 이(가) 엑셀 등에서 열려 있어 {alt.name} 로 저장했습니다.")
        return alt


def merge(out_dir, keep_duplicates=False):
    out_dir = Path(out_dir)
    raw_dir = out_dir / "raw"
    if not raw_dir.is_dir():
        say(f"[오류] raw 폴더가 없습니다: {raw_dir}")
        return 1

    # 이전에 끊겨 남은 임시파일 정리
    for p in list(out_dir.glob("*.tmp")) + list(raw_dir.glob("*/*.tmp")):
        try:
            p.unlink()
        except OSError:
            pass

    files = sorted(raw_dir.glob("*/*.csv"))
    if not files:
        say("합칠 파일이 없습니다.")
        return 1

    frames, bad, empty = [], [], 0
    for f in files:
        try:
            d = read_csv_auto(f)
        except Exception:
            bad.append(f"{f.parent.name}/{f.name}")
            continue
        if d.empty:
            empty += 1
            continue
        d.columns = [str(c).strip().lstrip("﻿") for c in d.columns]
        frames.append(d)
    if bad:
        say(f"  [!] 읽지 못한 파일 {len(bad)}개는 제외: {unicodedata.normalize('NFC', str(bad[:5]))}")
    if empty:
        say(f"  (내용이 빈 파일 {empty}개 제외)")
    if not frames:
        say("병합할 수 있는 파일이 없습니다.")
        return 1

    df = pd.concat(frames, ignore_index=True)
    for c in COLS:  # 빠진 컬럼이 있어도 계속 진행
        if c not in df.columns:
            df[c] = pd.NA
    extra = [c for c in df.columns if c not in COLS]
    df = df[COLS + extra]
    for c in ("사업장명",):  # 맥/윈도 한글 표기 차이(NFC/NFD) 통일
        df[c] = df[c].map(lambda s: unicodedata.normalize("NFC", s) if isinstance(s, str) else s)

    if not keep_duplicates:
        before = len(df)
        df = df.drop_duplicates(subset=KEY_COLS, keep="last").reset_index(drop=True)
        if before != len(df):
            say(f"  같은 사업장·일자·방류구 중복 {before - len(df):,}행 제거")

    out_raw = save_csv_atomic(df, out_dir / "tms_all_raw.csv")
    n_sites = df["사업장명"].nunique()
    say(f"원본 병합 완료: 파일 {len(frames)}개, 사업장 {n_sites}곳, {len(df):,}행 → {out_raw}")

    try:
        clean = df.copy()
        prov = pd.Series(False, index=clean.index)
        for c in VALUE_COLS:
            s = clean[c].fillna("").astype(str)
            prov |= s.str.contains("p", case=False)
            s = s.str.replace(r"[pP,\s]", "", regex=True).replace({"-": "", "–": ""})
            clean[c] = pd.to_numeric(s, errors="coerce")
        clean["잠정치포함"] = prov
        clean["날짜"] = pd.to_datetime(
            clean["연도"].astype(str) + clean["일자"].astype(str),
            format="%Y%m월%d일", errors="coerce",
        )
        badn = int(clean["날짜"].isna().sum())
        if badn:
            say(f"  [!] 날짜 변환 실패 {badn}행 (일자 형식 확인 필요)")
        out_clean = save_csv_atomic(clean, out_dir / "tms_all_clean.csv")
        say(f"정제본 저장 → {out_clean} (잠정치 포함 행 {int(prov.sum()):,})")
    except Exception as e:
        say(f"  [!] 정제본 생성 실패(원본 병합은 완료): {type(e).__name__}: {e}")
        return 1
    return 0


def main():
    fix_console_encoding()
    ap = argparse.ArgumentParser(description="수집된 사업장별 CSV 통합")
    ap.add_argument("--data-dir", default=None, help="data 폴더 (기본: 이 파일 옆의 data/)")
    ap.add_argument("--keep-duplicates", action="store_true", help="중복 행 제거하지 않음")
    a = ap.parse_args()
    out_dir = Path(a.data_dir) if a.data_dir else Path(__file__).resolve().parent / "data"
    try:
        sys.exit(merge(out_dir, a.keep_duplicates))
    except KeyboardInterrupt:
        say("중단됨")
        sys.exit(130)


if __name__ == "__main__":
    main()
