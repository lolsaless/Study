"""
한강홍수통제소 Open API 수집기 — 수위·유량 / 강수량(우량) 일자료와 관측소 제원

폴더 구성 (이 코드가 있는 폴더 기준)
    홍수통제소_수위유량.py                         이 코드
    홍수통제소.env                                 인증키  HRFCO_KEY=...
    raw_data/홍수통제소/waterlevel/<관측소코드>.csv  수위·유량 관측소별 일자료(받은 그대로, 이어 받기)
    raw_data/홍수통제소/rainfall/<관측소코드>.csv    우량 관측소별 일자료
    data/홍수통제소_수위유량_일자료.csv              결합: obscd, obs_name, date, wl_m, flow_cms, source
                                                    (연구 분석 폴더 data_weather/flow_daily.csv 와 같은 열)
    data/홍수통제소_우량_일자료.csv                  결합: stn("HR"+코드), stn_name, date, rain_mm, source
                                                    (weather_daily.csv 의 강수 부분과 같은 열)
    data/홍수통제소_대상관측소.csv                   이번에 받은 관측소 목록(종류·이름·좌표·자료 기간)
    data/홍수통제소_columns.csv                      열 이름 설명
    site_code/홍수통제소_수위관측소.csv              전체 수위 관측소 제원(info.json)
    site_code/홍수통제소_우량관측소.csv              전체 우량 관측소 제원

필요 패키지
    pip install requests pandas

실행
    python 홍수통제소_수위유량.py --test        관측소 1곳씩 7일만 받아 응답 형식 확인(처음에 꼭 실행)
    python 홍수통제소_수위유량.py --list        관측소 제원만 받아 BBOX 안 관측소 목록을 보여 줌
    python 홍수통제소_수위유량.py               설정한 기간·관측소 수집 → 결합
    python 홍수통제소_수위유량.py --merge-only  수집 없이 raw_data/홍수통제소 전체만 다시 결합

주의: 이 API 는 '실시간 자료'라 확정(검정) 전 값이 섞일 수 있다. 확정 자료는 국가수자원관리종합정보시스템(WAMIS)·수문조사연보.
"""

# ==================================================================
# ★ 설정 — 여기만 바꾸면 됩니다
# ==================================================================
START_DATE = "2024-01-01"   # 시작일
END_DATE = None             # 끝일 "2026-09-30" / None = 어제

GET_WATERLEVEL = True       # 수위·유량
GET_RAINFALL = True         # 강수량(우량계)

# 꼭 받을 관측소(제원 목록에 없어도 받음). 아래는 한탄강 수계 분석에서 쓰는 수위·유량 관측소
WL_CODES = [
    "1022648",   # 포천시(은현교)   — 포천 측정망
    "1022670",   # 연천군(신천교)   — 신천 측정망
    "1022680",   # 연천군(사랑교)   — 한탄강 = 사랑교 − 신천교
    "1022662",   # 연천군(차탄교)   — 미산 = 임진교 + 사랑교 + 차탄교
    "1021680",   # 연천군(임진교)
    "1022666",   # 고탄교 (유량이 전 기간 0 으로 기록되어 분석에서는 안 씀 — 확인용)
]
RF_CODES = []               # 꼭 받을 우량 관측소 코드

# 범위 안의 관측소를 제원(info.json) 좌표로 자동 추가. None 이면 위 목록만 받음
# (위도 최소, 위도 최대, 경도 최소, 경도 최대) — 기본값은 한탄강 수계(양주·동두천·포천·연천) 주변
BBOX = (37.80, 38.32, 126.85, 127.48)

ENV_FILE = "홍수통제소.env"
REFRESH_DAYS = 60           # 이미 받은 관측소도 마지막 날짜에서 이만큼 앞부터 다시 받음(실시간 자료 보정 반영)
CHUNK_DAYS = 31             # 한 번에 요청하는 기간(일). 오류·빈 응답이 잦으면 줄이고, 잘 되면 늘려도 됨
# ==================================================================

import argparse
import json
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, unquote

import pandas as pd
import requests

BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "raw_data" / "홍수통제소"
DATA_DIR = BASE_DIR / "data"
SITE_CODE_DIR = BASE_DIR / "site_code"

API = "https://api.hrfco.go.kr/{key}/{kind}/list/1D/{code}/{sdt}/{edt}.json"
INFO = "https://api.hrfco.go.kr/{key}/{kind}/info.json"
CODE_FIELD = {"waterlevel": "wlobscd", "rainfall": "rfobscd"}
VALUE_FIELDS = {"waterlevel": {"wl": "wl_m", "fw": "flow_cms"}, "rainfall": {"rf": "rain_mm"}}
TIME_FIELDS = ("ymd", "ymdh", "ymdhm")
DATE_FMTS = ["%Y%m%d", "%Y%m%d%H%M"]   # 1D 요청 날짜 형식 후보: 첫 번째가 빈 응답이면 두 번째로 다시 시도
SLEEP_SEC = 0.15
TIMEOUT = 60
MAX_RETRY = 4
KEY_NAMES = ["HRFCO_KEY", "HRFCO_API_KEY", "SERVICE_KEY", "SERVICEKEY", "API_KEY", "KEY"]
KIND_KO = {"waterlevel": "수위·유량", "rainfall": "우량"}


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
        sys.exit(f"[오류] {ENV_FILE} 파일이 코드 폴더({BASE_DIR})에 없습니다. 'HRFCO_KEY=인증키' 한 줄로 만드세요.")
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
    sys.exit(f"[오류] {ENV_FILE} 에서 인증키를 찾지 못했습니다. 'HRFCO_KEY=인증키' 로 적어 주세요.")


class AuthError(Exception):
    pass


def hide(text: str, key: str) -> str:
    return str(text).replace(key, "<인증키>")


def get_json(session: requests.Session, url: str, key: str) -> dict:
    """JSON 을 받아 dict 로. 인증 오류는 AuthError, 그 밖의 오류는 재시도 뒤 RuntimeError."""
    last = None
    for i in range(MAX_RETRY):
        try:
            r = session.get(url, timeout=TIMEOUT)
            body = r.content.decode("utf-8", errors="replace").strip()
            if r.status_code in (401, 403):
                raise AuthError(f"HTTP {r.status_code}: {body[:200]}")
            if r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            try:
                js = json.loads(body) if body else {}
            except json.JSONDecodeError:
                if re.search(r"(?i)(key|인증)", body[:300]):
                    raise AuthError(body[:200])
                raise ValueError(f"JSON 아님: {body[:150]}")
            msg = json.dumps(js, ensure_ascii=False)[:300] if isinstance(js, dict) and "content" not in js else ""
            if msg and re.search(r"(?i)(key|인증|권한)", msg):
                raise AuthError(msg)
            return js if isinstance(js, dict) else {"content": js}
        except AuthError:
            raise
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(hide(f"요청 실패({MAX_RETRY}회): {last}", key))


def chunks(d0: date, d1: date):
    a = d0
    while a <= d1:
        b = min(a + timedelta(days=CHUNK_DAYS - 1), d1)
        yield a, b
        a = b + timedelta(days=1)


def dms(x) -> float:
    """'127-03-25' 같은 도-분-초 표기를 십진수로. 이미 숫자면 그대로."""
    try:
        return float(x)
    except (TypeError, ValueError):
        p = [t for t in re.split(r"[-\s:°'\"]+", str(x).strip()) if t]
        try:
            v = [float(t) for t in p]
        except ValueError:
            return float("nan")
        return v[0] + v[1] / 60 + (v[2] if len(v) > 2 else 0) / 3600 if len(v) >= 2 else float("nan")


def lower_keys(rows) -> list[dict]:
    return [{str(k).lower(): v for k, v in r.items()} for r in (rows or []) if isinstance(r, dict)]


# ------------------------------------------------------------------
# 관측소 제원
# ------------------------------------------------------------------
def fetch_info(session, key, kind: str) -> pd.DataFrame:
    js = get_json(session, INFO.format(key=quote(key, safe=""), kind=kind), key)
    rows = lower_keys(js.get("content"))
    out = []
    for r in rows:
        code = str(r.get(CODE_FIELD[kind], "")).strip()
        if not code:
            continue
        out.append({"code": code, "name": nfc(str(r.get("obsnm", "")).strip()), "agency": nfc(str(r.get("agcnm", "")).strip()),
                    "lat": dms(r.get("lat")), "lon": dms(r.get("lon")),
                    "address": nfc(f"{r.get('addr', '') or ''} {r.get('etcaddr', '') or ''}".strip()),
                    "raw_lat": r.get("lat"), "raw_lon": r.get("lon")})
    df = pd.DataFrame(out)
    SITE_CODE_DIR.mkdir(exist_ok=True)
    name = {"waterlevel": "홍수통제소_수위관측소.csv", "rainfall": "홍수통제소_우량관측소.csv"}[kind]
    if len(df):
        df.to_csv(SITE_CODE_DIR / name, index=False, encoding="utf-8-sig")
    return df


def pick_targets(info: pd.DataFrame, fixed: list[str]) -> list[str]:
    codes = [str(c) for c in fixed]
    if BBOX is not None and len(info):
        a, b, c, d = BBOX
        inside = info[(info.lat.between(a, b)) & (info.lon.between(c, d))]
        codes += inside["code"].tolist()
    return list(dict.fromkeys(codes))


# ------------------------------------------------------------------
# 일자료
# ------------------------------------------------------------------
_fmt_ok: dict[str, str] = {}


def fetch_series(session, key, kind, code, d0: date, d1: date) -> pd.DataFrame:
    rows = []
    for a, b in chunks(d0, d1):
        fmts = [_fmt_ok[kind]] if kind in _fmt_ok else DATE_FMTS
        got = []
        for fmt in fmts:
            sdt = a.strftime(fmt)
            edt = (b.strftime(fmt) if fmt == "%Y%m%d" else (b.strftime("%Y%m%d") + "2350"))
            url = API.format(key=quote(key, safe=""), kind=kind, code=code, sdt=sdt, edt=edt)
            got = lower_keys(get_json(session, url, key).get("content"))
            time.sleep(SLEEP_SEC)
            if got:
                _fmt_ok.setdefault(kind, fmt)
                break
        rows += got
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    tcol = next((c for c in TIME_FIELDS if c in df.columns), None)
    if tcol is None:
        raise ValueError(f"시간 열({'/'.join(TIME_FIELDS)})이 없음. 받은 열: {list(df.columns)}")
    df.insert(0, "date", pd.to_datetime(df[tcol].astype(str).str[:8], format="%Y%m%d", errors="coerce").dt.strftime("%Y-%m-%d"))
    df["code"] = code
    return df.dropna(subset=["date"])


def raw_path(kind: str, code: str) -> Path:
    return RAW_DIR / kind / f"{code}.csv"


def collect_kind(session, key, kind, codes, d0: date, d1: date) -> None:
    (RAW_DIR / kind).mkdir(parents=True, exist_ok=True)
    plan = []
    for c in codes:
        p = raw_path(kind, c)
        a = d0
        if p.exists():
            old = pd.read_csv(p, dtype=str, encoding="utf-8-sig")
            if len(old) and old["date"].min() <= d0.isoformat():
                last = datetime.strptime(old["date"].max(), "%Y-%m-%d").date()
                a = max(d0, last - timedelta(days=REFRESH_DAYS))
        if a <= d1:
            plan.append((c, a))
    n_req = sum(len(list(chunks(a, d1))) for _, a in plan)
    print(f"\n[{KIND_KO[kind]}] 관측소 {len(plan)}/{len(codes)}곳 수집, 예상 요청 약 {n_req}번")
    for i, (c, a) in enumerate(plan, 1):
        try:
            new = fetch_series(session, key, kind, c, a, d1)
        except AuthError:
            raise
        except Exception as e:
            print(f"  {i}/{len(plan)} {c}: 실패 — {hide(e, key)}")
            continue
        p = raw_path(kind, c)
        if p.exists():
            old = pd.read_csv(p, dtype=str, encoding="utf-8-sig")
            new = pd.concat([old, new.astype(str)], ignore_index=True)
        if new.empty:
            print(f"  {i}/{len(plan)} {c}: 자료 없음")
            continue
        new = new.astype(str).drop_duplicates("date", keep="last").sort_values("date")
        new.to_csv(p, index=False, encoding="utf-8-sig")
        print(f"  {i}/{len(plan)} {c}: {a} ~ {d1} 받음 → 누적 {len(new):,}일 ({new['date'].min()} ~ {new['date'].max()})")


# ------------------------------------------------------------------
# 결합
# ------------------------------------------------------------------
def load_names(kind: str) -> dict:
    name = {"waterlevel": "홍수통제소_수위관측소.csv", "rainfall": "홍수통제소_우량관측소.csv"}[kind]
    p = find_file(name, (SITE_CODE_DIR,))
    if p is None:
        return {}
    df = pd.read_csv(p, dtype=str, encoding="utf-8-sig")
    return df.set_index("code").to_dict("index")


def merge_kind(kind: str) -> pd.DataFrame:
    folder = RAW_DIR / kind
    files = sorted(f for f in folder.glob("*.csv")) if folder.is_dir() else []
    if not files:
        return pd.DataFrame()
    df = pd.concat((pd.read_csv(f, dtype=str, encoding="utf-8-sig", keep_default_na=False) for f in files), ignore_index=True)
    for src, dst in VALUE_FIELDS[kind].items():
        v = df[src] if src in df.columns else pd.Series([""] * len(df))
        df[dst] = pd.to_numeric(v.astype(str).str.strip().replace({"": None, "-": None, "None": None, "nan": None}), errors="coerce")
    return df


def merge_all() -> int:
    DATA_DIR.mkdir(exist_ok=True)
    summary, ok = [], False
    wl = merge_kind("waterlevel")
    if len(wl):
        names = load_names("waterlevel")
        out = pd.DataFrame({"obscd": wl["code"], "obs_name": wl["code"].map(lambda c: names.get(c, {}).get("name", "")),
                            "date": wl["date"], "wl_m": wl["wl_m"], "flow_cms": wl["flow_cms"], "source": "HRFCO"})
        out = out.drop_duplicates(["obscd", "date"], keep="last").sort_values(["obscd", "date"])
        out.to_csv(DATA_DIR / "홍수통제소_수위유량_일자료.csv", index=False, encoding="utf-8-sig")
        ok = True
        print(f"\ndata/홍수통제소_수위유량_일자료.csv: {len(out):,}행, 관측소 {out.obscd.nunique()}곳, {out.date.min()} ~ {out.date.max()}")
        for c, g in out.groupby("obscd"):
            nm = names.get(c, {})
            summary.append({"kind": "수위·유량", "code": c, "name": nm.get("name", ""), "lat": nm.get("lat", ""), "lon": nm.get("lon", ""),
                            "address": nm.get("address", ""), "first": g.date.min(), "last": g.date.max(), "days": len(g),
                            "wl_days": int(g.wl_m.notna().sum()), "flow_days": int(g.flow_cms.notna().sum()),
                            "flow_zero_days": int((g.flow_cms == 0).sum())})
            print(f"  {c} {nm.get('name', ''):<16} {len(g):>5}일  수위 {int(g.wl_m.notna().sum()):>5}  유량 {int(g.flow_cms.notna().sum()):>5}"
                  f"  유량 0 {int((g.flow_cms == 0).sum()):>5}")
    rf = merge_kind("rainfall")
    if len(rf):
        names = load_names("rainfall")
        out = pd.DataFrame({"stn": "HR" + rf["code"], "stn_name": rf["code"].map(lambda c: names.get(c, {}).get("name", "")),
                            "date": rf["date"], "rain_mm": rf["rain_mm"], "source": "HRFCO"})
        out = out.drop_duplicates(["stn", "date"], keep="last").sort_values(["stn", "date"])
        out.to_csv(DATA_DIR / "홍수통제소_우량_일자료.csv", index=False, encoding="utf-8-sig")
        ok = True
        print(f"\ndata/홍수통제소_우량_일자료.csv: {len(out):,}행, 관측소 {out.stn.nunique()}곳, {out.date.min()} ~ {out.date.max()}")
        print(f"  강수 범위 {out.rain_mm.min()} ~ {out.rain_mm.max()} mm, 빈칸 {int(out.rain_mm.isna().sum()):,}행, 음수 {int((out.rain_mm < 0).sum())}행")
        for s, g in out.groupby("stn"):
            c = s[2:]
            nm = names.get(c, {})
            summary.append({"kind": "우량", "code": c, "name": nm.get("name", ""), "lat": nm.get("lat", ""), "lon": nm.get("lon", ""),
                            "address": nm.get("address", ""), "first": g.date.min(), "last": g.date.max(), "days": len(g),
                            "rain_days": int(g.rain_mm.notna().sum())})
    if not ok:
        print(f"[알림] raw_data/{RAW_DIR.name}/ 에 결합할 파일이 없습니다.")
        return 1
    pd.DataFrame(summary).convert_dtypes().to_csv(DATA_DIR / "홍수통제소_대상관측소.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([
        ("obscd", "수위 관측소 코드(wlobscd)", ""), ("obs_name", "관측소명(제원 obsnm)", ""), ("date", "관측일", "YYYY-MM-DD"),
        ("wl_m", "일 수위(API wl)", "m"), ("flow_cms", "일 유량(API fw). 수위만 재는 관측소는 빈칸 또는 0", "m³/s"),
        ("stn", "우량 관측소 = 'HR' + rfobscd (연구 weather_daily 형식)", ""), ("stn_name", "관측소명", ""),
        ("rain_mm", "일 강수량(API rf)", "mm"), ("source", "자료 출처 HRFCO(한강홍수통제소 실시간 API)", ""),
    ], columns=["열", "설명", "단위"]).to_csv(DATA_DIR / "홍수통제소_columns.csv", index=False, encoding="utf-8-sig")
    return 0


# ------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="한강홍수통제소 수위·유량·우량 일자료 수집")
    ap.add_argument("--merge-only", action="store_true", help="수집 없이 결합만")
    ap.add_argument("--test", action="store_true", help="관측소 1곳씩 7일만 받아 형식 확인")
    ap.add_argument("--list", action="store_true", help="관측소 제원만 받아 BBOX 안 목록 출력")
    a = ap.parse_args()
    if a.merge_only:
        return merge_all()

    key = read_key()
    s = requests.Session()
    yesterday = date.today() - timedelta(days=1)
    d0 = datetime.strptime(START_DATE, "%Y-%m-%d").date()
    d1 = min(datetime.strptime(END_DATE, "%Y-%m-%d").date(), yesterday) if END_DATE else yesterday
    kinds = [k for k, on in (("waterlevel", GET_WATERLEVEL), ("rainfall", GET_RAINFALL)) if on]

    try:
        targets = {}
        for kind in kinds:
            try:
                info = fetch_info(s, key, kind)
                print(f"[제원] {KIND_KO[kind]} 관측소 {len(info)}곳 → site_code/ 저장")
            except RuntimeError as e:
                print(f"[제원] {KIND_KO[kind]} 실패 — BBOX 자동 추가 없이 지정 코드만 받음: {e}")
                info = pd.DataFrame(columns=["code", "lat", "lon"])
            fixed = WL_CODES if kind == "waterlevel" else RF_CODES
            targets[kind] = pick_targets(info, fixed)
            if a.list:
                sel = info[info.code.isin(targets[kind])] if len(info) else info
                print(f"\n[{KIND_KO[kind]}] 대상 {len(targets[kind])}곳 (지정 {len(fixed)} + BBOX)")
                if len(sel):
                    print(sel[["code", "name", "agency", "lat", "lon", "address"]].to_string(index=False))
        if a.list:
            return 0

        if a.test:
            for kind in kinds:
                if not targets[kind]:
                    print(f"[시험] {KIND_KO[kind]}: 대상 관측소 없음")
                    continue
                c = targets[kind][0]
                t1 = yesterday - timedelta(days=1)
                t0 = t1 - timedelta(days=6)
                url = API.format(key=quote(key, safe=""), kind=kind, code=c, sdt=t0.strftime("%Y%m%d"), edt=t1.strftime("%Y%m%d"))
                js = get_json(s, url, key)
                print(f"\n[시험] {KIND_KO[kind]} {c} {t0} ~ {t1}")
                print(hide(json.dumps(js, ensure_ascii=False)[:600], key))
                df = fetch_series(s, key, kind, c, t0, t1)
                print(f"읽은 결과 {len(df)}행, 열 {list(df.columns)}")
                if len(df):
                    print(df.head(7).to_string(index=False))
                print(f"요청 날짜 형식: {_fmt_ok.get(kind, '응답 없음 — 두 형식 모두 빈 응답')}")
            return 0

        print(f"수집 기간 {d0} ~ {d1}")
        for kind in kinds:
            collect_kind(s, key, kind, targets[kind], d0, d1)
    except AuthError as e:
        sys.exit(f"[중단] 인증 오류로 보입니다. {ENV_FILE} 의 키를 확인하세요.\n  {hide(e, key)}")
    return merge_all()


if __name__ == "__main__":
    sys.exit(main())
