"""
물환경 수질측정망 운영결과 DB 수집기 — 대권역 '한강' 전 지점
(공공데이터포털 · 국립환경과학원 WaterQualityService / getWaterMeasuringList)

준비물 (이 코드와 같은 폴더)
    물환경.env                               공공데이터포털 인증키
    물환경_수질측정망_지점코드_전체.csv     지점 코드표 (CODE_FILE 로 이름 지정)

결과 (이 코드가 있는 폴더/data/)
    data/2025.csv, data/2026.csv ...   연도별 자료
    data/all_data.csv                  연도별 자료를 합친 파일
    data/columns.csv                   열 이름 설명
    data/sites_hangang.csv             수집 대상 지점 목록

필요 패키지
    pip install requests pandas

실행
    python fetch_water_measuring_hangang.py
"""

# ==================================================================
# ★ 설정 — 여기만 바꾸면 됩니다
# ==================================================================
START_YEAR = 2024          # 시작 연도
END_YEAR = 2024            # 끝 연도. None = 올해(최신 자료까지)
MONTHS = None              # 특정 월만: ["01", "02"] / None = 전체 월

BASIN = "한강"             # 대권역
SITE_TYPES = None          # 구분 제한: ["하천수", "호소수"] 등 / None = 전부
                           # (코드표 구분: 하천수·농업용수·호소수·산단하천·도시관류)

ENV_FILE = "물환경.env"
CODE_FILE = "물환경_수질측정망_지점코드_전체.csv"
# 코드표 파일명이 다르면 위 이름을 바꾸세요. 같은 폴더에 '지점코드'가 들어간 csv 가
# 하나뿐이면 이름이 달라도 자동으로 찾습니다.
# 필요한 열: 구분, 지점코드, 지점명, 대권역, 중권역 (조사기관·주소는 있으면 함께 저장)

REFRESH_DONE_YEARS = False  # True = 이미 받은 연도 파일도 다시 받기
                            # (올해 자료는 매달 늘어나므로 항상 다시 받음)
# ==================================================================

import os
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from urllib.parse import unquote

import pandas as pd
import requests

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

API_URL = "https://apis.data.go.kr/1480523/WaterQualityService/getWaterMeasuringList"
BATCH_SIZE = 10        # 한 번에 묻는 지점 수 (ptNoList 길이 제한 100자 → 7자리 코드 10개)
NUM_OF_ROWS = 1000
SLEEP_SEC = 0.3
TIMEOUT = 60
MAX_RETRY = 4

KEY_NAMES = ["DATA_GO_KR_API_KEY", "SERVICE_KEY", "SERVICEKEY", "API_KEY",
             "WATER_API_KEY", "KEY"]

# 응답 열 설명 (OpenAPI 활용가이드 2.1.3.2)
COLUMN_INFO = {
    "ptNo": ("조사지점코드", ""), "ptNm": ("조사지점명", ""), "addr": ("조사지점 주소", ""),
    "orgNm": ("조사기관명", ""), "wmyr": ("측정년도", ""), "wmod": ("측정월", ""),
    "wmwk": ("검사회차", ""), "wmdep": ("수심", "m"), "wmcymd": ("검사일자", ""),
    "lon": ("경도(십진수, 도분초 변환)", "°"), "lat": ("위도(십진수, 도분초 변환)", "°"),
    "itemLvl": ("수위", "m"), "itemAmnt": ("유량", "㎥/s"), "itemTemp": ("수온", "℃"),
    "itemPh": ("pH", "-"), "itemDoc": ("DO", "mg/L"), "itemBod": ("BOD", "mg/L"),
    "itemCod": ("COD", "mg/L"), "itemSs": ("SS", "mg/L"),
    "itemTcoli": ("총대장균군", "개/100mL"), "itemTn": ("T-N", "mg/L"), "itemTp": ("T-P", "mg/L"),
    "itemCd": ("카드뮴", "mg/L"), "itemCn": ("시안", "mg/L"), "itemPb": ("납", "mg/L"),
    "itemCr6": ("6가크롬", "mg/L"), "itemAs": ("비소", "mg/L"), "itemHg": ("수은", "mg/L"),
    "itemCu": ("구리", "mg/L"), "itemAbs": ("음이온계면활성제", "mg/L"), "itemPcb": ("PCB", "mg/L"),
    "itemOp": ("유기인", "mg/L"), "itemMn": ("용해성 망간", "mg/L"), "itemTrans": ("투명도", "m"),
    "itemCloa": ("클로로필-a", "mg/㎥"), "itemCl": ("염소이온", "mg/L"), "itemZn": ("아연", "mg/L"),
    "itemCr": ("크롬", "mg/L"), "itemFe": ("용해성 철", "mg/L"), "itemPhenol": ("페놀류", "mg/L"),
    "itemNhex": ("노말헥산추출물질", "mg/L"), "itemEc": ("전기전도도", "µS/cm"),
    "itemTce": ("트리클로로에틸렌", "mg/L"), "itemPce": ("테트라클로로에틸렌", "mg/L"),
    "itemNo3n": ("질산성질소", "mg/L"), "itemNh3n": ("암모니아성질소", "mg/L"),
    "itemEcoli": ("분원성대장균군", "개/100mL"), "itemPop": ("인산염인", "mg/L"),
    "itemDtn": ("용존총질소", "mg/L"), "itemDtp": ("용존총인", "mg/L"), "itemFl": ("불소", "mg/L"),
    "itemCol": ("색도", "도"), "itemCcl4": ("사염화탄소", "mg/L"),
    "itemDceth": ("1,2-다이클로로에탄", "mg/L"), "itemDcm": ("다이클로로메탄", "mg/L"),
    "itemBenzene": ("벤젠", "mg/L"), "itemChcl3": ("클로로포름", "mg/L"),
    "itemToc": ("TOC", "mg/L"), "itemDehp": ("DEHP", "mg/L"), "itemAntimon": ("안티몬", "mg/L"),
    "itemDiox": ("1,4-다이옥세인", "mg/L"), "itemHcho": ("포름알데히드", "mg/L"),
    "itemHcb": ("헥사클로로벤젠", "mg/L"), "itemNi": ("니켈", "mg/L"), "itemBa": ("바륨", "mg/L"),
    "itemSe": ("셀레늄", "mg/L"),
    "구분": ("코드표 구분(하천수·호소수 등)", ""), "중권역": ("코드표 중권역", ""),
}
# 투명도 단위는 명세서에 mg/L로 적혀 있으나 투명도는 보통 m 단위임(확인 필요)


# ------------------------------------------------------------------
# 파일 찾기 (맥의 한글 파일명 NFD/NFC 차이 대응)
# ------------------------------------------------------------------
def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def find_file(name: str, fallback_keyword: str | None = None, suffix: str = "") -> Path | None:
    target = nfc(name)
    for p in BASE_DIR.iterdir():
        if nfc(p.name) == target:
            return p
    if fallback_keyword:
        cands = [p for p in BASE_DIR.iterdir()
                 if fallback_keyword in nfc(p.name) and p.suffix.lower() == suffix]
        if len(cands) == 1:
            return cands[0]
    return None


# ------------------------------------------------------------------
# 인증키
# ------------------------------------------------------------------
def read_service_key() -> str:
    env_path = find_file(ENV_FILE)
    if env_path is None:
        sys.exit(f"[오류] {ENV_FILE} 파일이 코드 폴더({BASE_DIR})에 없습니다.")

    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            values[k.strip().upper()] = v.strip().strip('"').strip("'")

    key = next((values[k] for k in KEY_NAMES if values.get(k)), None)
    if key is None and len(values) == 1:          # 변수 하나뿐이면 그 값을 사용
        key = next(iter(values.values()))
    if not key:
        sys.exit(f"[오류] {ENV_FILE} 에서 인증키를 찾지 못했습니다. "
                 f"'DATA_GO_KR_API_KEY=키값' 형식으로 적어 주세요.")
    # 인코딩 키(%2F, %3D)를 넣었어도 되도록 디코딩 → requests 가 한 번만 인코딩
    return unquote(key) if "%" in key else key


# ------------------------------------------------------------------
# 지점 목록
# ------------------------------------------------------------------
def load_sites() -> pd.DataFrame:
    path = find_file(CODE_FILE, fallback_keyword="지점코드", suffix=".csv")
    if path is None:
        sys.exit(f"[오류] 코드표 '{CODE_FILE}' 가 코드 폴더에 없습니다.")

    # utf-8-sig(엑셀 'CSV UTF-8' 저장 포함) → 안 되면 cp949(엑셀 일반 CSV 저장)
    for enc in ("utf-8-sig", "cp949"):
        try:
            df = pd.read_csv(path, dtype=str, encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        sys.exit(f"[오류] 코드표 '{path.name}' 의 인코딩을 읽지 못했습니다.")

    df.columns = [str(c).strip() for c in df.columns]
    need = {"구분", "지점코드", "대권역", "중권역"}
    if not need <= set(df.columns):
        sys.exit(f"[오류] 코드표에 열 {sorted(need - set(df.columns))} 이 없습니다.")
    df = df.dropna(subset=["지점코드"])
    df = df.apply(lambda s: s.str.strip() if s.dtype == object else s)

    df = df[df["대권역"] == BASIN]
    if SITE_TYPES:
        df = df[df["구분"].isin(SITE_TYPES)]
    df = df.drop_duplicates("지점코드").reset_index(drop=True)
    if df.empty:
        sys.exit(f"[오류] 대권역 '{BASIN}' 지점이 코드표에 없습니다.")
    return df


# ------------------------------------------------------------------
# API
# ------------------------------------------------------------------
class ApiError(RuntimeError):
    pass


def parse_xml(text: str) -> tuple[list[dict], int]:
    root = ET.fromstring(text)
    if root.tag == "OpenAPI_ServiceResponse":           # 게이트웨이 오류(인증키 등)
        msg = root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg")
        raise ApiError(f"게이트웨이 오류: {msg}")

    code = (root.findtext(".//header/resultCode") or "").strip()
    msg = (root.findtext(".//header/resultMsg") or "").strip()
    if code not in ("00", "0", "000"):
        if code == "03" or "NODATA" in msg.upper().replace("_", ""):
            return [], 0
        raise ApiError(f"API 오류 {code}: {msg}")

    total = int(root.findtext(".//totalCount") or 0)
    rows = [{c.tag: (c.text or "").strip() for c in item} for item in root.iter("item")]
    return rows, total


def call_api(session: requests.Session, params: dict) -> tuple[list[dict], int]:
    last = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            r = session.get(API_URL, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            return parse_xml(r.text)
        except ApiError as e:
            if "SERVICE_KEY" in str(e) or "게이트웨이" in str(e):
                raise                                     # 키 문제는 재시도 무의미
            last = e
        except (requests.RequestException, ET.ParseError) as e:
            last = e
        time.sleep(2 * attempt)
    raise ApiError(f"{MAX_RETRY}회 실패: {last}")


def fetch_batch(session, key, codes: list[str], year: int) -> list[dict]:
    rows_all, page = [], 1
    while True:
        params = {
            "serviceKey": key, "numOfRows": NUM_OF_ROWS, "pageNo": page,
            "resultType": "xml", "ptNoList": ",".join(codes), "wmyrList": str(year),
        }
        if MONTHS:
            params["wmodList"] = ",".join(MONTHS)
        rows, total = call_api(session, params)
        rows_all.extend(rows)
        if not rows or len(rows_all) >= total:
            return rows_all
        page += 1
        time.sleep(SLEEP_SEC)


# ------------------------------------------------------------------
# 정리
# ------------------------------------------------------------------
TEXT_COLS = ["ptNo", "ptNm", "addr", "orgNm", "wmyr", "wmod", "wmwk", "wmcymd"]


def tidy(rows: list[dict], sites: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.drop(columns=["rowno"], errors="ignore")

    # 측정값·좌표 숫자로 (빈칸 → 결측)
    num_cols = [c for c in df.columns if c not in TEXT_COLS]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c].replace("", None), errors="coerce")

    # 도·분·초 → 십진수 좌표
    if {"lonDgr", "lonMin", "lonSec"} <= set(df.columns):
        df["lon"] = df["lonDgr"] + df["lonMin"] / 60 + df["lonSec"] / 3600
    if {"latDgr", "latMin", "latSec"} <= set(df.columns):
        df["lat"] = df["latDgr"] + df["latMin"] / 60 + df["latSec"] / 3600
    df = df.drop(columns=[c for c in df.columns if c[:3] in ("lon", "lat") and c[3:] in ("Dgr", "Min", "Sec")])

    df["wmcymd"] = pd.to_datetime(df["wmcymd"].str.replace(".", "-", regex=False),
                                  errors="coerce").dt.date
    df = df.merge(sites[["지점코드", "구분", "중권역"]].rename(columns={"지점코드": "ptNo"}),
                  on="ptNo", how="left")

    front = ["ptNo", "ptNm", "구분", "중권역", "orgNm", "addr", "lon", "lat",
             "wmyr", "wmod", "wmwk", "wmcymd", "wmdep"]
    front = [c for c in front if c in df.columns]
    items = sorted(c for c in df.columns if c.startswith("item"))
    rest = [c for c in df.columns if c not in front + items]
    df = df[front + items + rest]
    return df.drop_duplicates().sort_values(["ptNo", "wmcymd", "wmwk"]).reset_index(drop=True)


# ------------------------------------------------------------------
# 메인
# ------------------------------------------------------------------
def main() -> int:
    this_year = date.today().year
    end_year = END_YEAR or this_year
    years = list(range(START_YEAR, end_year + 1))

    key = read_service_key()
    sites = load_sites()
    codes = sites["지점코드"].tolist()
    batches = [codes[i:i + BATCH_SIZE] for i in range(0, len(codes), BATCH_SIZE)]

    DATA_DIR.mkdir(exist_ok=True)
    sites.to_csv(DATA_DIR / "sites_hangang.csv", index=False, encoding="utf-8-sig")
    print(f"대권역 {BASIN}: {len(codes)}개 지점 ({sites['구분'].value_counts().to_dict()})")
    print(f"연도 {years[0]}~{years[-1]}, 요청 묶음 {len(batches)}개/연도\n")

    with requests.Session() as s:
        for year in years:
            out = DATA_DIR / f"{year}.csv"
            partial = DATA_DIR / f"{year}_partial.csv"
            if out.exists() and not REFRESH_DONE_YEARS and year < this_year:
                print(f"[{year}] 이미 있음 → 건너뜀 (다시 받으려면 REFRESH_DONE_YEARS=True)")
                continue

            rows, failed = [], []
            for i, b in enumerate(batches, 1):
                try:
                    got = fetch_batch(s, key, b, year)
                    rows.extend(got)
                    print(f"  [{year}] {i:>3}/{len(batches)} {b[0]}~{b[-1]}: {len(got)}건")
                except ApiError as e:
                    print(f"  [{year}] {i:>3}/{len(batches)} 실패: {e}")
                    if "게이트웨이" in str(e) or "SERVICE_KEY" in str(e):
                        print("  → 인증키를 확인하세요. 중단합니다.")
                        return 1
                    failed.append(b)
                time.sleep(SLEEP_SEC)

            df = tidy(rows, sites)
            if df.empty:
                print(f"[{year}] 자료 없음\n")
                continue
            if failed:
                # 일부 실패 → 완성본으로 저장하지 않음(다음 실행 때 다시 받음)
                df.to_csv(partial, index=False, encoding="utf-8-sig")
                print(f"[{year}] {len(df):,}행 저장(일부 실패 {len(failed)}묶음) → {partial.name}\n")
            else:
                df.to_csv(out, index=False, encoding="utf-8-sig")
                partial.unlink(missing_ok=True)
                last = df["wmcymd"].max()
                print(f"[{year}] {len(df):,}행, {df['ptNo'].nunique()}개 지점, 최신 검사일 {last} → {out.name}\n")

    # ---- 연도별 파일 결합 ----
    files = [DATA_DIR / f"{y}.csv" for y in years if (DATA_DIR / f"{y}.csv").exists()]
    files += [DATA_DIR / f"{y}_partial.csv" for y in years
              if not (DATA_DIR / f"{y}.csv").exists() and (DATA_DIR / f"{y}_partial.csv").exists()]
    if not files:
        print("[알림] 결합할 자료가 없습니다.")
        return 1
    all_df = pd.concat((pd.read_csv(f, dtype={"ptNo": str, "wmyr": str, "wmod": str})
                        for f in sorted(files)), ignore_index=True)
    all_df.to_csv(DATA_DIR / "all_data.csv", index=False, encoding="utf-8-sig")

    cols = pd.DataFrame([(c, *COLUMN_INFO.get(c, ("", ""))) for c in all_df.columns],
                        columns=["열", "설명", "단위"])
    cols.to_csv(DATA_DIR / "columns.csv", index=False, encoding="utf-8-sig")

    print(f"완료: all_data.csv {len(all_df):,}행, {all_df['ptNo'].nunique()}개 지점 "
          f"(결합 파일: {', '.join(f.name for f in sorted(files))})")
    if any("partial" in f.name for f in files):
        print("[주의] 일부 실패한 연도가 섞여 있습니다. 다시 실행하면 그 연도를 다시 받습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
