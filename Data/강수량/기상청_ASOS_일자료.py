"""
기상청 지상관측(종관, ASOS) 일자료 수집기 — 기상청 API허브 (apihub.kma.go.kr)

폴더 구성 (이 코드가 있는 폴더 기준)
    기상청_ASOS_일자료.py                    이 코드
    기상청.env                               API허브 인증키  KMA_AUTH_KEY=...
    raw_data/기상청_ASOS/2024.csv ...        연도별 수집 자료(받은 그대로, 전국 또는 STATIONS)
    data/기상청_ASOS_일자료.csv               raw_data/기상청_ASOS 의 연도 파일 전체 결합(원래 열 56개 + 날짜·지점명)
    data/기상청_ASOS_weather_daily.csv        연구 분석 폴더 형식(stn, stn_name, date, rain_mm, source, ta_mean, ta_min, ta_max)
    data/기상청_ASOS_columns.csv              열 이름 설명
    site_code/기상청_ASOS_지점.csv            지점 정보(번호·이름·위경도). 지점정보 API 가 안 되면 코드 안 목록으로 대신함

필요 패키지
    pip install requests pandas

실행
    python 기상청_ASOS_일자료.py --test        한 달·응답 앞부분만 보고 끝냄(처음에 꼭 실행)
    python 기상청_ASOS_일자료.py               설정한 기간 수집 → 결합
    python 기상청_ASOS_일자료.py --merge-only  수집 없이 raw_data/기상청_ASOS 전체만 다시 결합

요청 수: 한 달에 1번(전국 지점을 한 번에 받음) → 2024-01 ~ 2026-11 이면 약 35번.
"""

# ==================================================================
# ★ 설정 — 여기만 바꾸면 됩니다
# ==================================================================
START_DATE = "2024-01-01"   # 시작일
END_DATE = None             # 끝일 "2026-09-30" / None = 어제(일자료는 전날까지)

STATIONS = []               # [] = 전국 ASOS 전체 저장
                            # 일부만: [95, 98, 99, 108]  (95 철원, 98 동두천, 99 파주, 108 서울)

ENV_FILE = "기상청.env"
REFRESH_DONE_YEARS = False  # True = 이미 받은 지난 연도도 다시 받기 (올해는 항상 다시 받음)

RAIN_NEG_AS_ZERO = True     # weather_daily 형식 파일에서 일강수량(RN_DAY)이 음수(-9 등)인 날을 0 으로 볼지
                            # (공공데이터포털 ASOS 는 '빈칸 = 비 안 옴'. API허브의 음수 코드가 같은 뜻인지는
                            #  첫 실행 요약의 'RN_DAY 값 분포'를 보고 확정할 것 → False 면 결측으로 둠)
# ==================================================================

import argparse
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote

import pandas as pd
import requests

BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "raw_data" / "기상청_ASOS"
DATA_DIR = BASE_DIR / "data"
SITE_CODE_DIR = BASE_DIR / "site_code"

DAY_URL = "https://apihub.kma.go.kr/api/typ01/url/kma_sfcdd3.php"     # 일자료 기간 조회
STN_URLS = [                                                            # 지점정보 (앞에서부터 시도)
    ("https://apihub.kma.go.kr/api/typ01/url/stn_inf.php", {"inf": "SFC", "stn": "", "help": "1"}),
    ("https://apihub.kma.go.kr/api/typ01/url/kma_stnlist.php", {"stn": "0", "help": "1"}),
]
SLEEP_SEC = 0.3
TIMEOUT = 90
MAX_RETRY = 4
KEY_NAMES = ["KMA_AUTH_KEY", "KMA_API_KEY", "AUTHKEY", "AUTH_KEY", "API_KEY", "KEY"]

# kma_sfcdd3.php 출력 열 (API허브 '지상관측 > 일자료' 출력결과 순서). 응답에 설명 줄이 있으면 그것을 우선 씀
COLUMNS = [
    ("TM", "관측일(KST)", ""), ("STN", "지점번호", ""),
    ("WS_AVG", "일 평균 풍속", "m/s"), ("WR_DAY", "일 풍정", "m"), ("WD_MAX", "최대풍향", "16방위"),
    ("WS_MAX", "최대풍속", "m/s"), ("WS_MAX_TM", "최대풍속 시각", "시분"), ("WD_INS", "최대순간풍향", "16방위"),
    ("WS_INS", "최대순간풍속", "m/s"), ("WS_INS_TM", "최대순간풍속 시각", "시분"),
    ("TA_AVG", "일 평균기온", "℃"), ("TA_MAX", "최고기온", "℃"), ("TA_MAX_TM", "최고기온 시각", "시분"),
    ("TA_MIN", "최저기온", "℃"), ("TA_MIN_TM", "최저기온 시각", "시분"),
    ("TD_AVG", "일 평균 이슬점온도", "℃"), ("TS_AVG", "일 평균 지면온도", "℃"), ("TG_MIN", "일 최저 초상온도", "℃"),
    ("HM_AVG", "일 평균 상대습도", "%"), ("HM_MIN", "최저습도", "%"), ("HM_MIN_TM", "최저습도 시각", "시분"),
    ("PV_AVG", "일 평균 수증기압", "hPa"), ("EV_S", "소형 증발량", "mm"), ("EV_L", "대형 증발량", "mm"),
    ("FG_DUR", "안개계속시간", "hr"), ("PA_AVG", "일 평균 현지기압", "hPa"), ("PS_AVG", "일 평균 해면기압", "hPa"),
    ("PS_MAX", "최고 해면기압", "hPa"), ("PS_MAX_TM", "최고 해면기압 시각", "시분"),
    ("PS_MIN", "최저 해면기압", "hPa"), ("PS_MIN_TM", "최저 해면기압 시각", "시분"),
    ("CA_TOT", "일 평균 전운량", "1/10"), ("SS_DAY", "일조합", "hr"), ("SS_DUR", "가조시간", "hr"),
    ("SS_CMB", "캄벨 일조", "hr"), ("SI_DAY", "일사합", "MJ/m²"), ("SI_60M_MAX", "최대 1시간일사", "MJ/m²"),
    ("SI_60M_MAX_TM", "최대 1시간일사 시각", "시분"), ("RN_DAY", "일 강수량", "mm"), ("RN_D99", "9-9 강수량", "mm"),
    ("RN_DUR", "강수계속시간", "hr"), ("RN_60M_MAX", "1시간 최다강수량", "mm"),
    ("RN_60M_MAX_TM", "1시간 최다강수량 시각", "시분"), ("RN_10M_MAX", "10분간 최다강수량", "mm"),
    ("RN_10M_MAX_TM", "10분간 최다강수량 시각", "시분"), ("RN_POW_MAX", "최대 강우강도", "mm/h"),
    ("RN_POW_MAX_TM", "최대 강우강도 시각", "시분"), ("SD_NEW", "최심 신적설", "cm"),
    ("SD_NEW_TM", "최심 신적설 시각", "시분"), ("SD_MAX", "최심 적설", "cm"), ("SD_MAX_TM", "최심 적설 시각", "시분"),
    ("TE_05", "0.5m 지중온도", "℃"), ("TE_10", "1.0m 지중온도", "℃"), ("TE_15", "1.5m 지중온도", "℃"),
    ("TE_30", "3.0m 지중온도", "℃"), ("TE_50", "5.0m 지중온도", "℃"),
]

# 지점정보 API 가 안 될 때 쓰는 이름표(경기·서울·강원 북부 위주). 좌표는 비워 둠
FALLBACK_NAMES = {
    90: "속초", 93: "북춘천", 95: "철원", 98: "동두천", 99: "파주", 100: "대관령", 101: "춘천",
    104: "북강릉", 105: "강릉", 108: "서울", 112: "인천", 114: "원주", 119: "수원", 121: "영월",
    201: "강화", 202: "양평", 203: "이천", 211: "인제", 212: "홍천", 216: "태백", 217: "정선군",
}


# ------------------------------------------------------------------
# 공통
# ------------------------------------------------------------------
def nfc(s) -> str:
    return unicodedata.normalize("NFC", str(s))


def find_file(name: str, folders=(BASE_DIR,)) -> Path | None:
    target = nfc(name)
    for folder in folders:
        if folder.is_dir():
            for p in folder.iterdir():
                if nfc(p.name) == target:
                    return p
    return None


def read_key() -> str:
    p = find_file(ENV_FILE)
    if p is None:
        sys.exit(f"[오류] {ENV_FILE} 파일이 코드 폴더({BASE_DIR})에 없습니다. 'KMA_AUTH_KEY=인증키' 한 줄로 만드세요.")
    vals = {}
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip().upper()] = v.strip().strip('"').strip("'")
    for k in KEY_NAMES:
        if vals.get(k):
            return unquote(vals[k])
    if len(vals) == 1:
        return unquote(next(iter(vals.values())))
    sys.exit(f"[오류] {ENV_FILE} 에서 인증키를 찾지 못했습니다. 'KMA_AUTH_KEY=인증키' 로 적어 주세요.")


def decode(raw: bytes) -> str:
    for enc in ("utf-8", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp949", errors="replace")


class KeyError_(Exception):
    pass


def get_text(session: requests.Session, url: str, params: dict) -> str:
    last = None
    for i in range(MAX_RETRY):
        try:
            r = session.get(url, params=params, timeout=TIMEOUT)
            text = decode(r.content)
            # API허브는 HTTP 200 에 JSON {"result":{"status":403,"message":"활용신청이 필요한 API 입니다…"}} 로 거절함
            m = re.search(r'"status"\s*:\s*(\d+).*?"message"\s*:\s*"([^"]*)"', text[:500], flags=re.S)
            if text.lstrip().startswith("{") and m and m.group(1) != "200":
                api = url.rsplit("/", 1)[-1]
                raise KeyError_(f"{api}: status {m.group(1)} — {m.group(2)}"
                                + (" → API허브에서 이 API 의 활용신청이 필요합니다" if "활용신청" in m.group(2) else ""))
            if r.status_code in (401, 403) or re.search(r"(?i)(auth|인증).{0,30}(fail|error|invalid|실패|오류|없)", text[:500]):
                raise KeyError_(f"HTTP {r.status_code}: {text[:300].strip()}")
            if r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            return text
        except KeyError_:
            raise
        except Exception as e:                       # 네트워크·서버 오류: 기다렸다가 다시
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"요청 실패({MAX_RETRY}회): {last}")


def month_ranges(d0: date, d1: date):
    a = d0
    while a <= d1:
        nxt = (a.replace(day=28) + timedelta(days=4)).replace(day=1)
        b = min(nxt - timedelta(days=1), d1)
        yield a, b
        a = b + timedelta(days=1)


# ------------------------------------------------------------------
# 응답 읽기
# ------------------------------------------------------------------
HELP_LINE = re.compile(r"^#\s*(\d+)\.\s*([A-Za-z0-9_]+)\s*:\s*(.*)$")


def parse_day_text(text: str) -> tuple[pd.DataFrame, list[str]]:
    """kma_sfcdd3 응답(# 설명 줄 + 공백/쉼표로 나뉜 값 줄)을 표로. 열 이름은 설명 줄 → 없으면 COLUMNS."""
    help_names, rows = [], []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            m = HELP_LINE.match(s)
            if m:
                help_names.append(m.group(2).upper())
            continue
        toks = [t.strip() for t in (s.split(",") if "," in s else s.split())]
        while toks and toks[-1] in ("", "="):
            toks.pop()
        if toks and re.fullmatch(r"\d{8,12}", toks[0]):
            rows.append(toks)
    names = help_names if len(help_names) >= 10 else [c[0] for c in COLUMNS]
    warn = []
    if not rows:
        return pd.DataFrame(columns=names), warn
    n = max(len(r) for r in rows)
    if n != len(names):
        warn.append(f"값 개수 {n}개 ≠ 열 이름 {len(names)}개 → 모자라는 열은 COL_번호로 저장")
        names = names[:n] + [f"COL_{i + 1}" for i in range(len(names), n)]
    df = pd.DataFrame([r + [""] * (n - len(r)) for r in rows], columns=names[:n])
    return df, warn


def parse_station_text(text: str) -> pd.DataFrame:
    """지점정보 응답에서 지점번호·위경도·한글 이름을 뽑는다(형식이 조금 달라도 읽히게)."""
    header = None
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            toks = s.lstrip("#").split()
            up = [t.upper() for t in toks]
            if ("STN_ID" in up or "STN" in up) and "LON" in up and "LAT" in up:
                header = up
            continue
        toks = [t for t in (s.split(",") if "," in s else s.split()) if t not in ("", "=")]
        if not toks or not re.fullmatch(r"\d{2,4}", toks[0]):
            continue
        rec = {}
        if header and len(toks) >= len(header):
            rec = dict(zip(header, toks))
        stn = int(toks[0])
        lon = rec.get("LON", toks[1] if len(toks) > 1 else "")
        lat = rec.get("LAT", toks[2] if len(toks) > 2 else "")
        name = rec.get("STN_KO") or next((t for t in toks[3:] if re.search(r"[가-힣]", t)), "")
        out.append({"stn": stn, "stn_name": nfc(name), "lat": pd.to_numeric(lat, errors="coerce"),
                    "lon": pd.to_numeric(lon, errors="coerce"), "height_m": pd.to_numeric(rec.get("HT", ""), errors="coerce"),
                    "basin": rec.get("BASIN", ""), "law_id": rec.get("LAW_ID", "")})
    df = pd.DataFrame(out)
    if len(df):
        df = df.drop_duplicates("stn", keep="last").sort_values("stn")
    return df


def fetch_stations(session, key, end: date) -> pd.DataFrame:
    for url, params in STN_URLS:
        p = dict(params, authKey=key)
        if "inf" in p:
            p["tm"] = end.strftime("%Y%m%d") + "2359"
        try:
            df = parse_station_text(get_text(session, url, p))
        except Exception as e:                       # 지점정보는 없어도 수집은 계속(활용신청 안 된 경우 포함)
            print(f"  [지점정보] {url.rsplit('/', 1)[-1]} 실패: {e}")
            continue
        if len(df) >= 10 and df.lat.notna().mean() > 0.5:
            print(f"  [지점정보] {url.rsplit('/', 1)[-1]}: {len(df)}개 지점")
            return df
        print(f"  [지점정보] {url.rsplit('/', 1)[-1]}: 형식을 읽지 못함(지점 {len(df)}개)")
    print("  [지점정보] API 로 받지 못해 코드 안 이름표(FALLBACK_NAMES)를 씀(좌표 없음)")
    return pd.DataFrame([{"stn": k, "stn_name": v} for k, v in FALLBACK_NAMES.items()])


# ------------------------------------------------------------------
# 수집
# ------------------------------------------------------------------
def fetch_period(session, key, d0: date, d1: date) -> tuple[pd.DataFrame, list[str]]:
    params = {"tm1": d0.strftime("%Y%m%d"), "tm2": d1.strftime("%Y%m%d"), "stn": "0", "help": "1", "authKey": key}
    text = get_text(session, DAY_URL, params)
    df, warn = parse_day_text(text)
    if df.empty and not re.search(r"^\s*#", text, flags=re.M):
        warn.append("응답에 자료도 설명 줄도 없음: " + text[:200].replace("\n", " "))
    if len(df) and STATIONS:
        df = df[pd.to_numeric(df["STN"], errors="coerce").isin([int(s) for s in STATIONS])]
    return df, warn


def collect(key: str, d0: date, d1: date) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    this_year = date.today().year
    years = list(range(d0.year, d1.year + 1))
    todo = []
    for y in years:
        done = find_file(f"{y}.csv", (RAW_DIR,))
        if done is not None and y < this_year and not REFRESH_DONE_YEARS:
            print(f"[{y}] 이미 있음 → 건너뜀 (다시 받으려면 REFRESH_DONE_YEARS = True)")
            continue
        todo.append(y)
    n_req = sum(len(list(month_ranges(max(d0, date(y, 1, 1)), min(d1, date(y, 12, 31))))) for y in todo)
    print(f"수집: {d0} ~ {d1}, 연도 {todo}, 예상 요청 {n_req}번 (+ 지점정보 1~2번)")

    for y in todo:
        a, b = max(d0, date(y, 1, 1)), min(d1, date(y, 12, 31))
        parts, failed = [], []
        for m0, m1 in month_ranges(a, b):
            try:
                df, warn = fetch_period(session, key, m0, m1)
            except KeyError_ as e:
                sys.exit(f"[중단] {e}\n  확인: {ENV_FILE} 의 키, API허브 > 지상관측 > 1.3 일자료(kma_sfcdd3) 활용신청")
            except RuntimeError as e:
                print(f"  [{y}-{m0.month:02d}] 실패: {e}")
                failed.append(m0.month)
                continue
            for w in warn:
                print(f"  [{y}-{m0.month:02d}] 주의: {w}")
            print(f"  [{y}-{m0.month:02d}] {len(df):,}행, 지점 {df['STN'].nunique() if len(df) else 0}곳")
            parts.append(df)
            time.sleep(SLEEP_SEC)
        out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        name = f"{y}_partial.csv" if failed else f"{y}.csv"
        if out.empty:
            print(f"[{y}] 받은 자료 없음 → 저장 안 함")
            continue
        out = out.drop_duplicates(["TM", "STN"], keep="last")
        out.to_csv(RAW_DIR / name, index=False, encoding="utf-8-sig")
        if not failed:
            old = find_file(f"{y}_partial.csv", (RAW_DIR,))
            if old is not None:
                old.replace(RAW_DIR / f"{y}_partial_old.csv")   # 완성본이 생기면 일부본은 결합에서 빠지게 이름만 바꿈
        print(f"[{y}] 저장 {RAW_DIR.name}/{name}: {len(out):,}행" + (f" (실패한 달 {failed})" if failed else ""))

    st = fetch_stations(session, key, d1)
    SITE_CODE_DIR.mkdir(exist_ok=True)
    st.to_csv(SITE_CODE_DIR / "기상청_ASOS_지점.csv", index=False, encoding="utf-8-sig")


# ------------------------------------------------------------------
# 결합
# ------------------------------------------------------------------
YEAR_FILE = re.compile(r"^(\d{4})(_partial)?\.csv$")


def merge_all() -> int:
    by_year: dict[str, Path] = {}
    if RAW_DIR.is_dir():
        for p in sorted(RAW_DIR.iterdir()):
            m = YEAR_FILE.match(nfc(p.name))
            if m and (m.group(1) not in by_year or not m.group(2)):
                by_year[m.group(1)] = p
    if not by_year:
        print(f"[알림] raw_data/{RAW_DIR.name}/ 에 결합할 연도 파일이 없습니다.")
        return 1
    df = pd.concat((pd.read_csv(by_year[y], dtype=str, keep_default_na=False) for y in sorted(by_year)), ignore_index=True)
    df["date"] = pd.to_datetime(df["TM"].str[:8], format="%Y%m%d", errors="coerce").dt.strftime("%Y-%m-%d")
    df["stn"] = pd.to_numeric(df["STN"], errors="coerce").astype("Int64")
    bad = df["date"].isna().sum()
    if bad:
        print(f"[주의] 날짜(TM)를 읽지 못한 행 {bad}개 — TM 앞 8자리가 YYYYMMDD 가 아닙니다. 예: {df.loc[df.date.isna(), 'TM'].head(3).tolist()}")
    df = df.drop_duplicates(["stn", "date"], keep="last")

    stp = find_file("기상청_ASOS_지점.csv", (SITE_CODE_DIR,))
    names = {}
    if stp is not None:
        st = pd.read_csv(stp, encoding="utf-8-sig")
        names = dict(zip(st["stn"].astype(int), st["stn_name"].astype(str)))
    for k, v in FALLBACK_NAMES.items():
        names.setdefault(k, v)
    df["stn_name"] = df["stn"].map(lambda s: names.get(int(s), "") if pd.notna(s) else "")

    raw_cols = [c for c in df.columns if c not in ("date", "stn", "stn_name")]
    df = df[["date", "stn", "stn_name"] + raw_cols].sort_values(["stn", "date"]).reset_index(drop=True)
    for c in raw_cols:
        if c not in ("TM",):
            df[c] = df[c].replace({"": None, "n/a": None, "N/A": None})
    DATA_DIR.mkdir(exist_ok=True)
    df.to_csv(DATA_DIR / "기상청_ASOS_일자료.csv", index=False, encoding="utf-8-sig")

    # 연구 분석 폴더 형식 (weather_data/weather_daily.csv 와 같은 열)
    num = lambda c: pd.to_numeric(df.get(c), errors="coerce")   # noqa: E731
    rn = num("RN_DAY")
    rain = rn.where(rn >= 0, 0.0 if RAIN_NEG_AS_ZERO else float("nan"))
    temp = lambda c: num(c).where(num(c) > -50)                 # noqa: E731  -99 등 결측 코드만 비움
    wd = pd.DataFrame({"stn": df["stn"], "stn_name": df["stn_name"], "date": df["date"], "rain_mm": rain,
                       "source": "ASOS", "ta_mean": temp("TA_AVG"), "ta_min": temp("TA_MIN"), "ta_max": temp("TA_MAX")})
    wd.to_csv(DATA_DIR / "기상청_ASOS_weather_daily.csv", index=False, encoding="utf-8-sig")

    info = {c: (d, u) for c, d, u in COLUMNS}
    info.update({"date": ("관측일(TM 앞 8자리)", "YYYY-MM-DD"), "stn": ("지점번호(숫자)", ""), "stn_name": ("지점명(지점정보 API)", "")})
    cols = pd.DataFrame([{"열": c, "설명": info.get(c, ("", ""))[0], "단위": info.get(c, ("", ""))[1]} for c in df.columns])
    cols["비고"] = ""
    cols.loc[cols["열"] == "RN_DAY", "비고"] = "음수(-9 등)는 결측 코드로 보임. weather_daily 에서는 RAIN_NEG_AS_ZERO 설정을 따름"
    cols.to_csv(DATA_DIR / "기상청_ASOS_columns.csv", index=False, encoding="utf-8-sig")

    # 요약
    print("\n=== 결합 결과 ===")
    print(f"data/기상청_ASOS_일자료.csv: {len(df):,}행, 지점 {df['stn'].nunique()}곳, 기간 {df['date'].min()} ~ {df['date'].max()}")
    print("연도별 행수:", df.groupby(df["date"].str[:4]).size().to_dict())
    print("사용한 파일:", [p.name for p in by_year.values()])
    if rn.notna().any():
        vc = rn.round(1).value_counts()
        neg = vc[vc.index < 0]
        print(f"RN_DAY 값 분포: 0.0 → {int(vc.get(0.0, 0)):,}행, 양수 → {int((rn > 0).sum()):,}행, "
              f"음수 → {dict((float(k), int(v)) for k, v in neg.items())}, 빈칸 → {int(rn.isna().sum()):,}행")
        print(f"  → weather_daily 의 음수 처리: {'0(비 안 옴)' if RAIN_NEG_AS_ZERO else '결측'} (RAIN_NEG_AS_ZERO)")
    for c in ("TA_AVG", "TA_MIN", "TA_MAX"):
        v = num(c)
        if v.notna().any():
            print(f"{c}: 범위 {v.min()} ~ {v.max()}, -50 이하(결측 코드로 보고 비움) {int((v <= -50).sum())}행")
    return 0


# ------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="기상청 API허브 ASOS 일자료 수집")
    ap.add_argument("--merge-only", action="store_true", help="수집 없이 결합만")
    ap.add_argument("--test", action="store_true", help="최근 한 달 응답만 확인")
    a = ap.parse_args()
    if a.merge_only:
        return merge_all()

    key = read_key()
    yesterday = date.today() - timedelta(days=1)
    d0 = datetime.strptime(START_DATE, "%Y-%m-%d").date()
    d1 = min(datetime.strptime(END_DATE, "%Y-%m-%d").date(), yesterday) if END_DATE else yesterday

    if a.test:
        m0 = (yesterday.replace(day=1) - timedelta(days=1)).replace(day=1)
        m1 = m0 + timedelta(days=6)
        print(f"[시험] {m0} ~ {m1}, 전국 지점")
        s = requests.Session()
        try:
            text = get_text(s, DAY_URL, {"tm1": m0.strftime("%Y%m%d"), "tm2": m1.strftime("%Y%m%d"),
                                         "stn": "0", "help": "1", "authKey": key})
        except KeyError_ as e:
            print("[인증 오류]", e)
            return 1
        lines = text.splitlines()
        print(f"응답 {len(lines)}줄. 앞 12줄과 첫 자료 2줄:")
        print("\n".join(lines[:12]))
        print("\n".join([l for l in lines if l.strip() and not l.lstrip().startswith("#")][:2]))
        df, warn = parse_day_text(text)
        print(f"\n읽은 결과: {len(df)}행 × {df.shape[1]}열, 지점 {df['STN'].nunique() if len(df) else 0}곳", *warn, sep="\n")
        if len(df):
            print(df[[c for c in ("TM", "STN", "TA_AVG", "TA_MIN", "TA_MAX", "RN_DAY") if c in df.columns]].head(5).to_string(index=False))
        st = fetch_stations(s, key, m1)
        print(st.head(5).to_string(index=False))
        return 0

    collect(key, d0, d1)
    return merge_all()


if __name__ == "__main__":
    sys.exit(main())
