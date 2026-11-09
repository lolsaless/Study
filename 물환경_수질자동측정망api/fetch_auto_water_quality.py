"""
수질자동측정망 운영결과 수집기 (공공데이터포털 · 국립환경과학원 WaterQualityService)

- 오퍼레이션 : getRealTimeWaterQualityList (수질자동측정망 운영결과 DB)
- 대상 지점  : 한강 S01001 가평 ~ S01025 양평 (23개소)
- 기간       : 2026-01-01 ~ 실행일 (공개 주기상 약 3개월 전까지 자료가 있음)
- 항목       : 수온, pH, 전기전도도, 용존산소, TOC, 클로로필-a, 총질소, 총인, 탁도 (시간자료)
- 인증키     : 이 코드와 같은 폴더의 .env 파일 → DATA_GO_KR_API_KEY
- 저장 위치  : 이 코드가 있는 폴더/raw_data/
    raw_data/by_site/<측정소코드>_<측정소명>_<YYYYMM>.csv   지점·월별 원자료(재실행 시 건너뜀)
    raw_data/수질자동측정망_시간자료_<시작>_<종료>.csv / .xlsx  전체 통합본

필요 패키지
    pip install requests pandas openpyxl python-dotenv

실행
    python fetch_auto_water_quality.py                 # 기본: 2026-01-01 ~ 오늘
    python fetch_auto_water_quality.py --end 2026-06-30
    python fetch_auto_water_quality.py --refresh       # 이미 받은 월도 다시 받기
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote

import pandas as pd
import requests

# ------------------------------------------------------------------
# 설정
# ------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent          # 코드가 있는 폴더
RAW_DIR = BASE_DIR / "raw_data"
SITE_DIR = RAW_DIR / "by_site"

API_URL = "https://apis.data.go.kr/1480523/WaterQualityService/getRealTimeWaterQualityList"

DEFAULT_START = date(2026, 1, 1)
NUM_OF_ROWS = 1000      # 한 달 시간자료 ≈ 744행 → 보통 1페이지
SLEEP_SEC = 0.3         # 요청 간 대기 (초당 최대 30건 제한)
TIMEOUT = 60
MAX_RETRY = 4

# 측정소 (수질자동측정망 운영결과 DB_물환경_코드_코드명.xlsx, 한강)
# ※ S01008, S01024 는 코드표에 없음 → 23개소
SITES = {
    "S01001": "가평",   "S01002": "흥천",   "S01003": "경안천", "S01004": "구리",
    "S01005": "여주",   "S01006": "원주",   "S01007": "평창강", "S01009": "한탄강",
    "S01010": "서상",   "S01011": "강천",   "S01012": "의암호", "S01013": "신천",
    "S01014": "충주",   "S01015": "인제",   "S01016": "미산",   "S01017": "포천",
    "S01018": "단양",   "S01019": "화천",   "S01020": "능서",   "S01021": "달천",
    "S01022": "복하천", "S01023": "청미천", "S01025": "양평",
}

# 항목별 후보 코드 (측정소마다 측정기 계열 1·2·3 중 쓰는 칸이 다름)
# 대표값은 왼쪽부터 처음으로 값이 있는 칸을 사용
ITEMS = {
    # 대표열 이름 : (후보 코드들, 단위, 국문명)
    "WT":    (["m02", "m38", "m69"], "℃",     "수온"),
    "pH":    (["m03", "m39", "m70"], "-",     "수소이온농도"),
    "EC":    (["m04", "m40", "m71"], "µS/cm", "전기전도도"),
    "DO":    (["m05", "m41", "m72"], "mg/L",  "용존산소"),
    "TOC":   (["m06", "m81"],        "mg/L",  "총유기탄소"),
    "ChlA":  (["m29"],               "mg/㎥", "클로로필-a"),
    "TN":    (["m27"],               "mg/L",  "총질소"),
    "TP":    (["m28"],               "mg/L",  "총인"),
    "TURB":  (["m79", "m80", "m73"], "NTU",   "탁도"),
}

CODE_NAMES = {
    "m01": "통신상태",
    "m02": "수온1", "m38": "수온2", "m69": "수온3",
    "m03": "pH1", "m39": "pH2", "m70": "pH3",
    "m04": "전기전도도1", "m40": "전기전도도2", "m71": "전기전도도3",
    "m05": "용존산소1", "m41": "용존산소2", "m72": "용존산소3",
    "m06": "총유기탄소1", "m81": "총유기탄소",
    "m29": "클로로필-a", "m27": "총질소", "m28": "총인",
    "m79": "탁도1", "m80": "탁도2", "m73": "탁도3",
}
KEEP_CODES = ["m01"] + [c for codes, _, _ in ITEMS.values() for c in codes]
META_COLS = ["siteId", "siteName", "msrDate"]


# ------------------------------------------------------------------
# .env / 인증키
# ------------------------------------------------------------------
def load_env() -> None:
    env_file = BASE_DIR / ".env"
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
        return
    except ImportError:
        pass
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def get_service_key() -> str:
    key = os.getenv("DATA_GO_KR_API_KEY", "").strip()
    if not key:
        sys.exit("[오류] .env 에 DATA_GO_KR_API_KEY 가 없습니다.")
    # 포털의 '인코딩' 키(%2F, %3D 포함)를 넣어도 되도록 한 번 디코딩.
    # requests 가 다시 인코딩하므로 이중 인코딩 오류가 나지 않음.
    return unquote(key) if "%" in key else key


# ------------------------------------------------------------------
# API 호출 (XML 응답 — 명세서에 정의된 형식)
# ------------------------------------------------------------------
class ApiError(RuntimeError):
    pass


def parse_xml(text: str) -> tuple[list[dict], int]:
    root = ET.fromstring(text)

    # 게이트웨이 오류 (인증키 오류, 트래픽 초과 등)
    if root.tag == "OpenAPI_ServiceResponse":
        msg = root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg")
        code = root.findtext(".//returnReasonCode")
        raise ApiError(f"게이트웨이 오류 {code}: {msg}")

    code = (root.findtext(".//header/resultCode") or "").strip()
    msg = (root.findtext(".//header/resultMsg") or "").strip()
    if code not in ("00", "0", "000"):
        if code in ("03",) or "NODATA" in msg.upper().replace("_", ""):
            return [], 0
        raise ApiError(f"API 오류 {code}: {msg}")

    total = int(root.findtext(".//body/totalCount") or root.findtext(".//totalCount") or 0)
    rows = []
    for item in root.iter("item"):
        rows.append({child.tag: (child.text or "").strip() for child in item})
    return rows, total


def call_api(session: requests.Session, params: dict) -> tuple[list[dict], int]:
    last = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            r = session.get(API_URL, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            return parse_xml(r.text)
        except ApiError as e:
            # 인증키 문제는 재시도해도 소용없음
            if any(k in str(e) for k in ("SERVICE_KEY", "인증", "UNREGISTERED", "DEADLINE")):
                raise
            last = e
        except (requests.RequestException, ET.ParseError) as e:
            last = e
        time.sleep(2 * attempt)
    raise ApiError(f"{MAX_RETRY}회 실패: {last}")


def fetch_site_period(session, key, site_id, d0: date, d1: date) -> list[dict]:
    rows_all: list[dict] = []
    page = 1
    while True:
        params = {
            "serviceKey": key,
            "numOfRows": NUM_OF_ROWS,
            "pageNo": page,
            "resultType": "xml",
            "siteId": site_id,
            "startDate": d0.strftime("%Y%m%d") + "000000",
            "endDate": d1.strftime("%Y%m%d") + "235959",
        }
        rows, total = call_api(session, params)
        rows_all.extend(rows)
        if not rows or len(rows_all) >= total:
            break
        page += 1
        time.sleep(SLEEP_SEC)
    return rows_all


# ------------------------------------------------------------------
# 정리
# ------------------------------------------------------------------
def tidy(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for c in META_COLS + KEEP_CODES:
        if c not in df.columns:
            df[c] = pd.NA
    df = df[META_COLS + KEEP_CODES].copy()

    # 'n/a', 빈칸 → 결측 / 숫자 변환
    for c in KEEP_CODES:
        df[c] = pd.to_numeric(df[c].replace({"n/a": None, "N/A": None, "": None}),
                              errors="coerce")
    df["datetime"] = pd.to_datetime(df["msrDate"], errors="coerce")
    return df


def add_representative(df: pd.DataFrame) -> pd.DataFrame:
    """항목별 대표열 + 어느 칸에서 왔는지(_src) 표시."""
    for name, (codes, _, _) in ITEMS.items():
        val = pd.Series(pd.NA, index=df.index, dtype="Float64")
        src = pd.Series(pd.NA, index=df.index, dtype="object")
        for c in codes:
            fill = val.isna() & df[c].notna()
            val[fill] = df.loc[fill, c]
            src[fill] = c
        df[name] = val
        df[f"{name}_src"] = src
    return df


def month_ranges(start: date, end: date):
    cur = date(start.year, start.month, 1)
    while cur <= end:
        nxt = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        yield max(cur, start), min(nxt - timedelta(days=1), end)
        cur = nxt


# ------------------------------------------------------------------
# 메인
# ------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=DEFAULT_START.isoformat(), help="YYYY-MM-DD")
    ap.add_argument("--end", default=date.today().isoformat(), help="YYYY-MM-DD")
    ap.add_argument("--refresh", action="store_true", help="받은 월도 다시 받기")
    args = ap.parse_args()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    load_env()
    key = get_service_key()
    SITE_DIR.mkdir(parents=True, exist_ok=True)

    months = list(month_ranges(start, end))
    print(f"기간 {start} ~ {end} | 측정소 {len(SITES)}개 × {len(months)}개월")

    failed = []
    with requests.Session() as s:
        for sid, sname in SITES.items():
            for d0, d1 in months:
                out = SITE_DIR / f"{sid}_{sname}_{d0:%Y%m}.csv"
                # 이번 달·지난달 등 아직 갱신 중일 수 있는 달은 매번 다시 받음
                recent = d1 >= date.today().replace(day=1) - timedelta(days=100)
                if out.exists() and not args.refresh and not recent:
                    continue
                try:
                    rows = fetch_site_period(s, key, sid, d0, d1)
                except ApiError as e:
                    print(f"  {sid} {sname} {d0:%Y-%m} 실패: {e}")
                    failed.append((sid, sname, f"{d0:%Y-%m}", str(e)))
                    if "SERVICE_KEY" in str(e) or "인증" in str(e):
                        print("  → 인증키를 확인하세요. 중단합니다.")
                        return 1
                    continue
                df = tidy(rows)
                if df.empty:
                    print(f"  {sid} {sname} {d0:%Y-%m}: 자료 없음(미공개 기간일 수 있음)")
                    continue
                df.to_csv(out, index=False, encoding="utf-8-sig")
                print(f"  {sid} {sname} {d0:%Y-%m}: {len(df):>4}행")
                time.sleep(SLEEP_SEC)

    # ---- 통합본 ----
    files = sorted(SITE_DIR.glob("*.csv"))
    if not files:
        print("[알림] 받은 자료가 없습니다.")
        return 1
    df = pd.concat((pd.read_csv(f, dtype={"siteId": str}) for f in files), ignore_index=True)
    df["datetime"] = pd.to_datetime(df["msrDate"], errors="coerce")
    df = df[(df["datetime"] >= pd.Timestamp(start))
            & (df["datetime"] < pd.Timestamp(end) + pd.Timedelta(days=1))]
    df = (df.drop_duplicates(subset=["siteId", "msrDate"])
            .sort_values(["siteId", "datetime"]).reset_index(drop=True))
    df = add_representative(df)

    rep_cols = list(ITEMS)
    order = (["siteId", "siteName", "datetime", "msrDate", "m01"] + rep_cols
             + [f"{c}_src" for c in rep_cols]
             + [c for codes, _, _ in ITEMS.values() for c in codes])
    df = df[order]

    tag = f"{start:%Y%m%d}_{df['datetime'].max():%Y%m%d}"
    csv_path = RAW_DIR / f"수질자동측정망_시간자료_{tag}.csv"
    xlsx_path = RAW_DIR / f"수질자동측정망_시간자료_{tag}.xlsx"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    # 항목 설명표
    dict_rows = [("siteId", "측정소코드", ""), ("siteName", "측정소명", ""),
                 ("datetime", "측정일시", ""), ("m01", "통신상태", "")]
    for name, (codes, unit, kor) in ITEMS.items():
        dict_rows.append((name, f"{kor} 대표값 ({' → '.join(codes)} 순으로 첫 값)", unit))
        dict_rows.append((f"{name}_src", f"{kor} 대표값의 원 코드", ""))
    for c, n in CODE_NAMES.items():
        if c != "m01":
            dict_rows.append((c, n, ""))
    dict_rows.append(("※", "값 -999 = 정량한계 미만 (원값 그대로 보존)", ""))
    info = pd.DataFrame(dict_rows, columns=["열", "설명", "단위"])

    # 지점별 자료 현황
    avail = (df.groupby(["siteId", "siteName"])
               .agg(시작=("datetime", "min"), 종료=("datetime", "max"), 행수=("datetime", "size"),
                    **{f"{k}_결측률": (k, lambda s: round(s.isna().mean() * 100, 1))
                       for k in rep_cols})
               .reset_index())

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="시간자료", index=False)
        avail.to_excel(w, sheet_name="지점별현황", index=False)
        info.to_excel(w, sheet_name="열설명", index=False)
        if failed:
            pd.DataFrame(failed, columns=["siteId", "siteName", "월", "오류"]) \
              .to_excel(w, sheet_name="실패목록", index=False)

    print(f"\n완료: {len(df):,}행, {df['siteId'].nunique()}개 측정소, "
          f"{df['datetime'].min():%Y-%m-%d} ~ {df['datetime'].max():%Y-%m-%d %H:%M}")
    print(f"  CSV : {csv_path}\n  XLSX: {xlsx_path}")
    if failed:
        print(f"[주의] 실패 {len(failed)}건 — 다시 실행하면 실패한 달만 이어서 받습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
