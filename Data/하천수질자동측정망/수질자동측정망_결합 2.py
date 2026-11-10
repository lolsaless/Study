# -*- coding: utf-8 -*-
"""
수질자동측정망 자료 결합

입력 (이 코드와 같은 폴더)
  - 한강_일별.csv                : 2026-01-01 ~ 2026-08-31 일평균 자료
  - 수질자동측정망_시간자료.csv   : 2024 ~ 2025 일별 집계 자료 (항목별 _mean 사용)

출력
  - ./data/수질자동측정망_일.csv
    컬럼: 측정소, 날짜, 연도, 월, 일, WT, pH, EC, DO, 탁도, TOC, 총질소, 총인, 클로로필-a
"""

from pathlib import Path

import pandas as pd

# ------------------------------------------------------------------
# 경로 설정 (코드가 있는 폴더 기준)
# ------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
FILE_HANGANG = BASE_DIR / "한강_일별.csv"
FILE_HOURLY = BASE_DIR / "수질자동측정망_시간자료.csv"
OUT_DIR = BASE_DIR / "data"
OUT_FILE = OUT_DIR / "수질자동측정망_일.csv"

# ------------------------------------------------------------------
# 컬럼 매핑 (원본 컬럼명 -> 최종 컬럼명)
# ------------------------------------------------------------------
# 한강_일별.csv
MAP_HANGANG = {
    "siteName": "측정소",
    "msrDate": "날짜",
    "WT": "WT",
    "pH": "pH",
    "EC": "EC",
    "DO": "DO",
    "TURB": "탁도",
    "TOC": "TOC",
    "TN": "총질소",
    "TP": "총인",
    "ChlA": "클로로필-a",
}

# 수질자동측정망_시간자료.csv (평균값만 사용)
MAP_HOURLY = {
    "측정소": "측정소",
    "날짜": "날짜",
    "WT_mean": "WT",
    "pH_mean": "pH",
    "EC_mean": "EC",
    "DO_mean": "DO",
    "Turb_mean": "탁도",
    "TOC_mean": "TOC",
    "TN_mean": "총질소",
    "TP_mean": "총인",
    "Chl_a_mean": "클로로필-a",
}

VALUE_COLS = ["WT", "pH", "EC", "DO", "탁도", "TOC", "총질소", "총인", "클로로필-a"]
FINAL_COLS = ["측정소", "날짜", "연도", "월", "일"] + VALUE_COLS


def read_csv_auto(path: Path, usecols) -> pd.DataFrame:
    """utf-8-sig -> cp949 순서로 인코딩을 시도하며 필요한 컬럼만 읽는다."""
    if not path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")
    last_err = None
    for enc in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(path, usecols=list(usecols), encoding=enc)
        except UnicodeDecodeError as e:
            last_err = e
    raise last_err


def load_and_rename(path: Path, mapping: dict) -> pd.DataFrame:
    df = read_csv_auto(path, mapping.keys())
    df = df.rename(columns=mapping)[list(mapping.values())]
    df["날짜"] = pd.to_datetime(df["날짜"], errors="coerce")
    df["측정소"] = df["측정소"].astype(str).str.strip()
    for c in VALUE_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def main():
    df_hg = load_and_rename(FILE_HANGANG, MAP_HANGANG)
    df_hr = load_and_rename(FILE_HOURLY, MAP_HOURLY)

    # 결합 (2024~2025 + 2026)
    df = pd.concat([df_hr, df_hg], ignore_index=True)
    df = df.dropna(subset=["날짜"])

    # 연·월·일 컬럼 생성
    df["연도"] = df["날짜"].dt.year
    df["월"] = df["날짜"].dt.month
    df["일"] = df["날짜"].dt.day

    # 같은 측정소·날짜가 겹치면 나중 값(한강_일별) 유지
    df = df.drop_duplicates(subset=["측정소", "날짜"], keep="last")

    df = df[FINAL_COLS].sort_values(["측정소", "날짜"]).reset_index(drop=True)
    df["날짜"] = df["날짜"].dt.strftime("%Y-%m-%d")

    # 저장 (엑셀에서 한글이 깨지지 않도록 utf-8-sig)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_FILE, index=False, encoding="utf-8-sig")

    print(f"저장 완료: {OUT_FILE}")
    print(f"행 수: {len(df):,} / 측정소 수: {df['측정소'].nunique()}")
    print(f"기간: {df['날짜'].min()} ~ {df['날짜'].max()}")


if __name__ == "__main__":
    main()
