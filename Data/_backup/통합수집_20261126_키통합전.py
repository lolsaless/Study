# -*- coding: utf-8 -*-
"""한탄강 연구 범위 통합 수집기 (Study/Data/통합수집.py, 2026-11-26)

흐름
  1) 수집   : 각 주제 폴더의 수집 코드를 '연구 범위 + 저장 위치(total/)'만 바꿔 실행한다.
              기존 주제 폴더의 자료(크롤링 원자료 등)는 건드리지 않는다.
  2) total/ : 연구 범위 자료를 2024년부터 '받은 그대로(원본 형태)' 모아 둔다. 처음 실행 때 기존 수집 자료에서
              범위 안 것만 복사해 채우고(시드), 그 뒤로는 새로 받은 자료가 덧붙는다.
  3) 연구사업 반영 : total/ 을 바탕으로 연구사업/data_tms·data_weather 의 분석용 파일을 지금과 같은 열·형식으로
              갱신한다. 기본은 '덧붙이기' — 기존 행은 그대로, 지점마다 기존 마지막 날 다음 자료만 붙인다.
              (분석 기간은 연구사업 config.END 가 정하므로, END 를 바꾸기 전까지 분석 결과는 같다)

total/ 구조 (주제 폴더 이름 그대로)
  total/하천수질자동측정망/raw_data/한강_일별_2024_2025.csv   2024~25 확정 일자료(범위 4곳, 한강_일별.csv 의 열 그대로)
                         /raw_data/by_site/<코드>_<이름>_<월>.csv  2026 API 원자료(지점·월별)
                         /data/data_수질자동측정망.csv          결합본(연구사업 수질자동측정망_data.csv 와 같은 열)
  total/하수폐수자동측정망/raw/<분기>/<사업장>.csv            soosiro 크롤링 원표(문자열 그대로), site_list_*.csv, tms_all_raw·clean.csv
  total/강수량/raw_data/기상청_ASOS/<연도>.csv               API허브 원자료(범위 지점만), data/ 결합본
  total/수위/raw_data/홍수통제소/<waterlevel|rainfall>/<코드>.csv  홍수통제소 원자료, data/ 결합본

쓰는 법 (맥미니·윈도우 공통, 인터넷 되는 PC)
  python 통합수집.py --check              # 받지 않고 total/·연구사업 자료가 어디까지 있는지 표로 보기
  python 통합수집.py --test               # 하천·기상·수위 API 연결만 확인(파일 안 바꿈)
  python 통합수집.py                      # 하천(2026)·기상·수위 수집 → total/ → 연구사업 덧붙이기
  python 통합수집.py --tms 2026Q4         # 방류수 TMS 그 분기만 크롤링(크롬 필요) → total/ → 연구사업
  python 통합수집.py --tms 2026Q4 --tms-refresh   # 이미 받은 사업장도 다시(잠정치 p → 확정치)
  python 통합수집.py --only river         # 일부만(river·weather·level)
  python 통합수집.py --merge-only         # 받지 않고 total/ 결합 + 연구사업 반영만
  python 통합수집.py --no-research        # 연구사업 폴더는 건드리지 않음
  python 통합수집.py --research-overwrite # 연구사업 파일의 겹치는 날짜도 total 값으로 바꿈(분석 결과가 바뀔 수 있음)
  python 통합수집.py --init-total         # total/ 에 빠진 시드 파일을 기존 수집 자료에서 다시 채움

인증키는 각 주제 폴더의 .env 를 그대로 쓴다(이 파일은 키를 출력하지 않는다). 결과 요약: 통합수집_요약.md
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path

import pandas as pd

# ==================================================================
# ★ 연구 범위 — 여기만 바꾸면 됩니다
# ==================================================================
SCOPE_NAME = "한탄강 수계 (양주·동두천·포천·연천)"

# 하천 수질자동측정망 (분석 config.RIVER_STATIONS 와 같은 4곳)
RIVER_SITES = {"S01017": "포천", "S01009": "한탄강", "S01013": "신천", "S01016": "미산"}
RIVER_START = "2026-01-01"          # 2024·2025 는 확정 자료(한강_일별)를 시드로 씀. 새로 받는 것은 2026 부터
RIVER_REFRESH = True                # 2026 은 확정 전이라 받은 달도 매번 다시 받음

# 방류수 TMS: 사업장 이름에 이 말이 들어간 곳(분석 config.SIGUN_KEYS 와 같음, 2026Q3 목록 기준 39곳)
TMS_SITE_KEYS = ["양주", "동두천", "포천", "연천"]
TMS_EXCLUDE_KEYS = ["남양주"]
TMS_FIRST_YEAR = 2024

# 기상청 ASOS: 철원(95)·동두천(98)은 분석에 쓰는 지점, 파주(99)는 예비
ASOS_STATIONS = [95, 98, 99]
ASOS_START = "2024-01-01"

# 홍수통제소: 꼭 받을 수위·유량 관측소 + 범위(BBOX) 안 관측소 자동 추가
#   뒤쪽 5곳(파주 1023667~1023680)은 BBOX 밖이지만 분석 h00 이 '임진강 하류 중권역'으로 고르는 관측소
LEVEL_WL_CODES = ["1022648", "1022670", "1022680", "1022662", "1021680", "1022666",
                  "1023667", "1023670", "1023671", "1023677", "1023680"]
LEVEL_BBOX = [37.80, 38.32, 126.85, 127.48]
LEVEL_START = "2024-01-01"
# ==================================================================

HERE = Path(__file__).resolve().parent
SUMMARY = HERE / "통합수집_요약.md"
LOG = []


def nfc(s):
    return unicodedata.normalize("NFC", str(s))


def find(base, *parts):
    """맥(NFD)·윈도우(NFC) 한글 이름 차이와 상관없이 하위 경로를 찾는다. 없으면 None."""
    if base is None:
        return None
    p = Path(base)
    for name in parts:
        q = p / name
        if not q.exists() and p.is_dir():
            q = next((x for x in p.iterdir() if nfc(x.name) == nfc(name)), q)
        if not q.exists():
            return None
        p = q
    return p


def sub(base, *parts):
    """total/ 아래 경로: 있으면 그 경로(NFD 여부 무관), 없으면 NFC 이름으로 만들 경로."""
    p = Path(base)
    for name in parts:
        q = find(p, name) if p.exists() else None
        p = q if q is not None else p / nfc(name)
    return p


def say(msg=""):
    print(msg, flush=True)
    LOG.append(msg)


def read(p, **kw):
    return pd.read_csv(p, encoding="utf-8-sig", low_memory=False, **kw)


def save(df, p):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    os.replace(tmp, p)


def py_env():
    return dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")


# ── 경로 ─────────────────────────────────────────────
SRC_RIVER = find(HERE, "하천수질자동측정망")
SRC_RIVER_FETCH = find(SRC_RIVER, "2026", "fetch_auto_water_quality.py")
SRC_TMS = find(HERE, "하수폐수자동측정망", "tms_crawling")
SRC_ASOS = find(HERE, "강수량")
SRC_LEVEL = find(HERE, "수위")

TOTAL = sub(HERE, "total")
T_RIVER = TOTAL / nfc("하천수질자동측정망")
T_TMS = TOTAL / nfc("하수폐수자동측정망")
T_ASOS = TOTAL / nfc("강수량")
T_LEVEL = TOTAL / nfc("수위")


def T(base, *parts):
    return sub(base, *parts)


# 주제 폴더 코드를 '설정만 바꿔' 별도 파이썬으로 실행하는 작은 실행기. *_DIR 값은 경로로 바꿔 넣는다.
RUNNER = r"""
import importlib.util, json, sys
from pathlib import Path
path, over = sys.argv[1], json.loads(sys.argv[2])
sys.argv = [path] + sys.argv[3:]
spec = importlib.util.spec_from_file_location("collector", path)
m = importlib.util.module_from_spec(spec); sys.modules["collector"] = m; spec.loader.exec_module(m)
for k, v in over.items():
    if k.endswith("_DIR"):
        v = Path(v)
    elif k == "BBOX" and v is not None:
        v = tuple(v)
    setattr(m, k, v)
sys.exit(m.main() or 0)
"""


def run_collector(path: Path, overrides: dict, args=()):
    show = {k: v for k, v in overrides.items() if not k.endswith("_DIR")}
    say(f"  실행: {path.parent.name}/{path.name} {' '.join(args)}  (범위: {show}, 저장: total/)")
    js = json.dumps({k: str(v) if isinstance(v, Path) else v for k, v in overrides.items()}, ensure_ascii=False)
    r = subprocess.run([sys.executable, "-c", RUNNER, str(path), js, *args], cwd=path.parent, env=py_env())
    if r.returncode != 0:
        say(f"  [!] {path.name} 가 오류로 끝남(코드 {r.returncode}) — 화면 메시지를 확인하세요")
    return r.returncode == 0


def load_module(path, name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def tms_scope(name):
    n = nfc(name)
    for k in TMS_EXCLUDE_KEYS:
        n = n.replace(nfc(k), "")
    return any(nfc(k) in n for k in TMS_SITE_KEYS)


# ==================================================================
# 0. total/ 시드: 기존 수집 자료에서 범위 안 것만 복사(이미 있는 파일은 건드리지 않음)
# ==================================================================
def copy_missing(src: Path, dst: Path):
    if dst.exists() or find(dst.parent, dst.name) is not None:
        return 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return 1


def init_total():
    say("\n## 0. total/ 시드 (기존 수집 자료 → 범위 안 것만, 2024~)")
    TOTAL.mkdir(parents=True, exist_ok=True)
    readme = TOTAL / "README.md"
    if not readme.exists():
        readme.write_text("# total/ — 한탄강 연구 범위 원자료 모음\n\n`Study/Data/통합수집.py` 가 만들고 덧붙인다. "
                          "손으로 고치지 않는다. 설명은 `Study/Data/통합수집_안내.md`.\n", encoding="utf-8")
    n = {}
    # 하천: 2024~25 확정 일자료(범위 4곳) + 2026 by_site 원자료
    daily = find(SRC_RIVER, "한강_일별.csv")
    out = T(T_RIVER, "raw_data", "한강_일별_2024_2025.csv")
    if daily is not None and not out.exists():
        d = read(daily)
        d = d[d["측정소"].astype(str).map(nfc).isin([nfc(v) for v in RIVER_SITES.values()])]
        save(d, out)
        n["하천 2024~25 일자료 행"] = f"{len(d):,}"
    bs = find(SRC_RIVER, "2026", "raw_data", "by_site")
    if bs is not None:
        n["하천 2026 by_site 파일"] = sum(copy_missing(f, T(T_RIVER, "raw_data", "by_site") / nfc(f.name))
                                       for f in bs.glob("*.csv") if f.name[:6] in RIVER_SITES)
    # 방류수 TMS: 분기별 사업장 원표(범위 안), 사업장 목록, 확인된 빈 결과
    src = find(SRC_TMS, "data")
    if src is not None and (src / "raw").exists():
        k = 0
        for tag in sorted(p for p in (src / "raw").iterdir()
                          if p.is_dir() and p.name[:4].isdigit() and int(p.name[:4]) >= TMS_FIRST_YEAR):
            T(T_TMS, "raw", tag.name).mkdir(parents=True, exist_ok=True)
            k += sum(copy_missing(f, T(T_TMS, "raw", tag.name) / nfc(f.name)) for f in tag.glob("*.csv") if tms_scope(f.stem))
        for f in src.glob("site_list_*.csv"):
            copy_missing(f, T_TMS / nfc(f.name))
        ce = find(src, "confirmed_empty.csv")
        if ce is not None and not (T_TMS / "confirmed_empty.csv").exists():
            c = read(ce, dtype=str)
            save(c[c["site_name"].map(tms_scope)], T_TMS / "confirmed_empty.csv")
        n["TMS 사업장 파일"] = k
    # 기상 ASOS: 연도 원자료 중 범위 지점만
    rawa = find(SRC_ASOS, "raw_data", "기상청_ASOS")
    if rawa is not None:
        k = 0
        for f in sorted(rawa.glob("*.csv")):
            if not f.stem.isdigit() or int(f.stem) < int(ASOS_START[:4]):
                continue
            dst = T(T_ASOS, "raw_data", "기상청_ASOS") / f.name
            if dst.exists():
                continue
            d = read(f, dtype=str)
            save(d[pd.to_numeric(d["STN"], errors="coerce").isin(ASOS_STATIONS)], dst)
            k += 1
        st = find(SRC_ASOS, "site_code", "기상청_ASOS_지점.csv")
        if st is not None:
            copy_missing(st, T(T_ASOS, "site_code") / nfc("기상청_ASOS_지점.csv"))
        n["ASOS 연도 파일"] = k
    # 수위: 관측소별 원자료(수위 폴더가 이미 한탄강 범위로 받고 있음)
    rawl = find(SRC_LEVEL, "raw_data", "홍수통제소")
    if rawl is not None:
        k = 0
        for kind in ("waterlevel", "rainfall"):
            if (rawl / kind).exists():
                k += sum(copy_missing(f, T(T_LEVEL, "raw_data", "홍수통제소", kind) / f.name) for f in (rawl / kind).glob("*.csv"))
        sc = find(SRC_LEVEL, "site_code")
        for f in (sc.glob("*.csv") if sc is not None else []):
            copy_missing(f, T(T_LEVEL, "site_code") / nfc(f.name))
        n["홍수통제소 관측소 파일"] = k
    say("  새로 복사: " + (", ".join(f"{a} {b}" for a, b in n.items()) or "없음(이미 있음)"))


# ==================================================================
# 1. 하천 수질자동측정망
# ==================================================================
MAP_DAILY = {"측정소": "측정소", "날짜": "날짜", "WT_mean": "WT", "pH_mean": "pH", "EC_mean": "EC", "DO_mean": "DO",
             "Turb_mean": "탁도", "TOC_mean": "TOC", "TN_mean": "총질소", "TP_mean": "총인", "Chl_a_mean": "클로로필-a"}
MAP_2026 = {"siteName": "측정소", "msrDate": "날짜", "WT": "WT", "pH": "pH", "EC": "EC", "DO": "DO", "TURB": "탁도",
            "TOC": "TOC", "TN": "총질소", "TP": "총인", "ChlA": "클로로필-a"}
VALUE_COLS = ["WT", "pH", "EC", "DO", "탁도", "TOC", "총질소", "총인", "클로로필-a"]
FINAL_COLS = ["측정소", "날짜", "연도", "월", "일"] + VALUE_COLS


def river_2026_table(site_dir: Path):
    """by_site 원자료 → 항목 대표값 표(수집 코드의 add_representative 그대로 사용)."""
    fm = load_module(SRC_RIVER_FETCH, "river_fetch")
    files = sorted(site_dir.glob("*.csv")) if site_dir.exists() else []
    if not files:
        return None
    df = pd.concat((pd.read_csv(f, dtype={"siteId": str}, encoding="utf-8-sig") for f in files), ignore_index=True)
    df["datetime"] = pd.to_datetime(df["msrDate"], errors="coerce")
    df = df.drop_duplicates(subset=["siteId", "msrDate"], keep="last").sort_values(["siteId", "datetime"]).reset_index(drop=True)
    df = fm.add_representative(df)
    rep = list(fm.ITEMS)
    order = (["siteId", "siteName", "datetime", "msrDate", "m01"] + rep + [f"{c}_src" for c in rep]
             + [c for codes, _, _ in fm.ITEMS.values() for c in codes])
    df = df[[c for c in order if c in df.columns]]
    df["datetime"] = df["datetime"].dt.strftime("%Y-%m-%d")
    return df


def river_combine(daily_path: Path, site_dir: Path):
    """2024~25 일자료(_mean 열) + 2026 대표값 → 결합본. 규칙은 수질자동측정망_결합.py 와 같음(겹치면 2026 우선)."""
    t26 = river_2026_table(site_dir)
    if daily_path is None or not Path(daily_path).exists() or t26 is None:
        return None, None
    a = read(daily_path, usecols=list(MAP_DAILY)).rename(columns=MAP_DAILY)
    b = t26[list(MAP_2026)].rename(columns=MAP_2026)
    out = []
    for d in (a, b):
        d = d.copy()
        d["날짜"] = pd.to_datetime(d["날짜"], errors="coerce")
        d["측정소"] = d["측정소"].astype(str).str.strip()
        for c in VALUE_COLS:
            d[c] = pd.to_numeric(d[c], errors="coerce")
        out.append(d)
    df = pd.concat(out, ignore_index=True).dropna(subset=["날짜"])
    df["연도"], df["월"], df["일"] = df["날짜"].dt.year, df["날짜"].dt.month, df["날짜"].dt.day
    df = df.drop_duplicates(subset=["측정소", "날짜"], keep="last")
    df = df[FINAL_COLS].sort_values(["측정소", "날짜"]).reset_index(drop=True)
    df["날짜"] = df["날짜"].dt.strftime("%Y-%m-%d")
    return df, t26


def total_river_data():
    df, t26 = river_combine(T(T_RIVER, "raw_data", "한강_일별_2024_2025.csv"), T(T_RIVER, "raw_data", "by_site"))
    if df is None:
        say("  [!] total 하천 결합 재료가 없습니다")
        return
    save(t26, T(T_RIVER, "data", "수질자동측정망_2026.csv"))
    save(df, T(T_RIVER, "data", "data_수질자동측정망.csv"))
    say(f"  total 하천 결합: data_수질자동측정망.csv {len(df):,}행, {df['측정소'].nunique()}곳, {df['날짜'].min()} ~ {df['날짜'].max()}")


def step_river(a):
    say("\n## 1. 하천 수질자동측정망 (2026)")
    if SRC_RIVER_FETCH is None:
        say("  [!] 하천수질자동측정망/2026/fetch_auto_water_quality.py 가 없습니다")
        return
    if a.test:
        fm = load_module(SRC_RIVER_FETCH, "river_fetch")
        fm.load_env()
        key = fm.get_service_key()
        import requests
        sid = next(iter(RIVER_SITES))
        t = date.today()
        m = (t.year * 12 + t.month - 1) - 4
        d0 = date(m // 12, m % 12 + 1, 1)                  # 넉 달 전 달(공개 지연 고려)
        try:
            with requests.Session() as s:
                rows = fm.fetch_site_period(s, key, sid, d0, d0.replace(day=7))
        except Exception as e:  # 오류 문장에 주소(인증키 포함)가 들어갈 수 있어 가린다
            msg = str(e)
            for k in {key, requests.utils.quote(key, safe=""), requests.utils.quote(key)}:
                msg = msg.replace(k, "***")
            say(f"  [시험 실패] {msg[:300]}")
            return
        say(f"  [시험] {sid} {RIVER_SITES[sid]} {d0} ~ {d0.replace(day=7)}: {len(rows)}행 받음 (파일은 안 바꿈)")
        return
    if not a.merge_only:
        args = ["--start", RIVER_START, "--end", date.today().isoformat()] + (["--refresh"] if RIVER_REFRESH else [])
        run_collector(SRC_RIVER_FETCH, {"SITES": RIVER_SITES, "RAW_DIR": T(T_RIVER, "raw_data"),
                                        "SITE_DIR": T(T_RIVER, "raw_data", "by_site")}, args)
    total_river_data()


# ==================================================================
# 2. 방류수 TMS (soosiro 크롤링)
# ==================================================================
def tms_merge(data_dir: Path):
    """raw/<분기>/*.csv → (원표 문자열 그대로, 정제본). 정제 규칙은 크롤러 merge_all 과 같음(잠정치 p 분리·숫자·날짜)."""
    raw_dir = find(data_dir, "raw")
    files = sorted(raw_dir.glob("*/*.csv")) if raw_dir is not None else []
    if not files:
        return None, None
    frames = []
    for f in files:
        try:
            frames.append(pd.read_csv(f, dtype=str, encoding="utf-8-sig"))
        except Exception:
            say(f"  [!] 읽지 못한 파일: {f.name}")
    raw = pd.concat(frames, ignore_index=True)
    clean = raw.copy()
    prov = pd.Series(False, index=clean.index)
    for c in raw.columns[6:]:
        s = clean[c].fillna("").astype(str)
        prov |= s.str.contains("p", case=False)
        clean[c] = pd.to_numeric(s.str.replace(r"[pP,\s]", "", regex=True).replace({"-": "", "–": ""}), errors="coerce")
    clean["잠정치포함"] = prov
    clean["날짜"] = pd.to_datetime(clean["연도"].astype(str) + clean["일자"].astype(str), format="%Y%m월%d일", errors="coerce")
    return raw, clean


def total_tms_data():
    raw, clean = tms_merge(T_TMS)
    if raw is None:
        say("  [!] total TMS 원자료가 없습니다")
        return
    save(raw, T_TMS / "tms_all_raw.csv")
    save(clean, T_TMS / "tms_all_clean.csv")
    say(f"  total TMS 결합: tms_all_raw.csv {len(raw):,}행, 사업장 {raw['사업장명'].nunique()}곳, "
        f"{clean['날짜'].min():%Y-%m-%d} ~ {clean['날짜'].max():%Y-%m-%d}, 잠정치 포함 행 {int(clean['잠정치포함'].sum()):,}")


def step_tms(a):
    say("\n## 2. 방류수 TMS (soosiro 크롤링)")
    crawler = find(SRC_TMS, "soosiro_tms_4.py")
    if crawler is None:
        say("  [!] 하수폐수자동측정망/tms_crawling/soosiro_tms_4.py 가 없습니다")
        return
    if not a.merge_only:
        for tag in a.tms:
            tag = tag.upper().replace(" ", "")
            if len(tag) != 6 or tag[4] != "Q" or not tag[:4].isdigit() or tag[5] not in "1234":
                say(f"  [!] 분기 형식이 틀림: {tag} (예: 2026Q4)")
                continue
            T_TMS.mkdir(parents=True, exist_ok=True)
            args = ["--years", tag[:4], "--quarters", tag[5], "--data-dir", str(T_TMS),
                    "--site-keys", *TMS_SITE_KEYS, "--exclude-keys", *TMS_EXCLUDE_KEYS]
            args += (["--refresh"] if a.tms_refresh else []) + (["--show"] if a.tms_show else []) \
                + (["--include-open"] if a.tms_include_open else [])
            say(f"  실행: soosiro_tms_4.py --years {tag[:4]} --quarters {tag[5]} --data-dir total/하수폐수자동측정망 "
                f"--site-keys {' '.join(TMS_SITE_KEYS)}" + (" --refresh" if a.tms_refresh else ""))
            say("  (분기가 끝나기 전이면 크롤러가 건너뜀. 부분 자료라도 받으려면 --tms-include-open)")
            subprocess.run([sys.executable, str(crawler), *args], cwd=crawler.parent, env=py_env())
    total_tms_data()


def tms_status(data_dir, tag):
    raw = find(data_dir, "raw", tag)
    sl = find(data_dir, f"site_list_{tag}.csv")
    n_scope = int(read(sl)["site_name"].map(tms_scope).sum()) if sl is not None else None
    files = [f for f in raw.glob("*.csv") if tms_scope(f.stem)] if raw is not None else []
    prov = 0
    for f in files:
        try:
            d = pd.read_csv(f, dtype=str, encoding="utf-8-sig")
            prov += int(d.iloc[:, 6:].apply(lambda c: c.fillna("").str.contains("p", case=False)).any(axis=1).sum())
        except Exception:
            pass
    return n_scope, len(files), prov


# ==================================================================
# 3·4. 기상청 ASOS, 홍수통제소
# ==================================================================
def step_weather(a):
    say("\n## 3. 기상청 ASOS 일자료")
    p = find(SRC_ASOS, "기상청_ASOS_일자료.py")
    if p is None:
        say("  [!] 강수량/기상청_ASOS_일자료.py 가 없습니다")
        return
    args = ["--test"] if a.test else (["--merge-only"] if a.merge_only else [])
    run_collector(p, {"STATIONS": ASOS_STATIONS, "START_DATE": ASOS_START,
                      "RAW_DIR": T(T_ASOS, "raw_data", "기상청_ASOS"), "DATA_DIR": T(T_ASOS, "data"),
                      "SITE_CODE_DIR": T(T_ASOS, "site_code")}, args)


def step_level(a):
    say("\n## 4. 홍수통제소 수위·유량·우량")
    p = find(SRC_LEVEL, "홍수통제소_수위유량.py")
    if p is None:
        say("  [!] 수위/홍수통제소_수위유량.py 가 없습니다")
        return
    args = ["--test"] if a.test else (["--merge-only"] if a.merge_only else [])
    run_collector(p, {"WL_CODES": LEVEL_WL_CODES, "BBOX": LEVEL_BBOX, "START_DATE": LEVEL_START,
                      "RAW_DIR": T(T_LEVEL, "raw_data", "홍수통제소"), "DATA_DIR": T(T_LEVEL, "data"),
                      "SITE_CODE_DIR": T(T_LEVEL, "site_code")}, args)


# ==================================================================
# 5. 연구사업 반영: total/ → 연구사업/data_tms, data_weather (같은 열·형식, 덧붙이기)
# ==================================================================
def backup_research(p: Path, stamp: str):
    bk = p.parent / "_backup" / stamp
    bk.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, bk / p.name)


def append_by_station(old, new, st_key, rest_keys, overwrite):
    """old(문자열)는 그대로 두고, new 중 '그 지점의 old 마지막 날 다음' 행만 뒤에 붙인다.
    old 에 없는 지점은 old 전체의 마지막 날 다음부터. 날짜는 열 '__d', 지점 구분은 st_key 함수로 만든 '__k'.
    overwrite=True 면 (지점, rest_keys) 가 겹치는 old 행의 값을 new 값으로 바꾼다."""
    cols = list(old.columns)
    o = old.copy()
    n = new.copy()
    o["__k"], n["__k"] = st_key(o), st_key(n)
    kc = ["__k"] + rest_keys
    n = n.drop_duplicates(kc, keep="last")
    replaced = 0
    if overwrite:
        nv = n.set_index(kc)
        oi = o.set_index(kc).index
        hit = oi.isin(nv.index)
        if hit.any():
            vc = [c for c in cols if c not in rest_keys]
            o.loc[hit, vc] = nv.loc[oi[hit], vc].values
            replaced = int(hit.sum())
    last = o.groupby("__k")["__d"].max()
    cut = n["__k"].map(last).fillna(o["__d"].max())
    add = n[n["__d"] > cut].sort_values(["__k", "__d"])
    out = pd.concat([o[cols], add[cols]], ignore_index=True)
    return out, len(add), replaced


def research_river(R_TMS, stamp, overwrite):
    src = T(T_RIVER, "data", "data_수질자동측정망.csv")
    dst = find(R_TMS, "수질자동측정망_data.csv")
    if not src.exists() or dst is None:
        say("  [!] 하천: total 결합본 또는 연구사업 data_tms/수질자동측정망_data.csv 가 없음")
        return
    old, new = read(dst, dtype=str), read(src, dtype=str)
    old["__d"], new["__d"] = old["날짜"], new["날짜"]
    out, nadd, nrep = append_by_station(old, new[list(old.columns)], lambda d: d["측정소"].map(nfc), ["날짜"], overwrite)
    say(f"  하천 → data_tms/수질자동측정망_data.csv: 붙인 행 {nadd:,}, 바꾼 행 {nrep:,} (전 {len(old):,} → {len(out):,})")
    if nadd or nrep:
        backup_research(dst, stamp)
        save(out.drop(columns=["__d"]), dst)


def research_tms(R_TMS, stamp, overwrite):
    raw, _ = tms_merge(T_TMS)
    dst = find(R_TMS, "하수폐수측정망_data.csv")
    if raw is None or dst is None:
        say("  [!] TMS: total 원자료 또는 연구사업 data_tms/하수폐수측정망_data.csv 가 없음")
        return
    old = read(dst, dtype=str)
    new = raw.copy()
    for c in new.columns[6:]:          # 연구사업 파일은 잠정치 표시(p) 없는 숫자 문자열
        new[c] = new[c].fillna("").astype(str).str.replace(r"[pP,\s]", "", regex=True).replace({"-": "", "–": ""})
    fmt = "%Y%m월%d일"
    old["__d"] = pd.to_datetime(old["연도"] + old["일자"], format=fmt, errors="coerce")
    new["__d"] = pd.to_datetime(new["연도"] + new["일자"], format=fmt, errors="coerce")
    key = lambda d: d["사업장명"].map(nfc) + "|" + d["방류구"].astype(str)  # noqa: E731
    out, nadd, nrep = append_by_station(old, new[list(old.columns)], key, ["연도", "분기", "일자"], overwrite)
    say(f"  TMS → data_tms/하수폐수측정망_data.csv: 붙인 행 {nadd:,}, 바꾼 행 {nrep:,} (전 {len(old):,} → {len(out):,})")
    if nadd or nrep:
        backup_research(dst, stamp)
        save(out.drop(columns=["__d"]), dst)


def research_dir(a):
    return Path(a.research) if a.research else find(HERE.parent.parent, "연구사업")


def step_research(a):
    say("\n## 5. 연구사업 반영 (total/ → data_tms·data_weather, 덧붙이기"
        + (", 겹치는 날 덮어쓰기" if a.research_overwrite else "") + ")")
    R = research_dir(a)
    R_TMS, R_W = find(R, "data_tms"), find(R, "data_weather")
    if R_TMS is None or R_W is None:
        say("  [!] 연구사업/data_tms·data_weather 를 찾지 못함(Study 와 연구사업이 나란히 있어야 함, 또는 --research 경로)")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    research_river(R_TMS, stamp, a.research_overwrite)
    research_tms(R_TMS, stamp, a.research_overwrite)
    m = find(R_W, "merge_from_study.py")
    if m is None:
        say("  [!] 연구사업/data_weather/merge_from_study.py 가 없음")
    else:
        args = ["--apply", "--study", str(TOTAL)] + (["--overwrite"] if a.research_overwrite else [])
        r = subprocess.run([sys.executable, str(m), *args], cwd=m.parent, env=py_env(), capture_output=True,
                           text=True, encoding="utf-8")
        say("  기상·유량 → data_weather (merge_from_study.py):")
        for ln in (r.stdout or "").splitlines():
            if ln.startswith("- "):
                say("    " + ln)
        if r.returncode != 0:
            say(f"  [!] merge_from_study.py 오류: {(r.stderr or '')[-300:]}")
    say(f"  바뀐 연구사업 파일의 이전 판: 각 폴더 _backup/{stamp}/ (바뀐 것이 있을 때만, 기상·유량은 data_weather/_backup/)")


# ==================================================================
# 현황 표
# ==================================================================
def span_rows(label, f, key, date_col, keys=None):
    if f is None or not Path(f).exists():
        return [(label, "-", "(파일 없음)", "", "")]
    d = read(f, usecols=[key, date_col], dtype={key: str})
    if keys is not None:
        d = d[d[key].astype(str).map(nfc).isin([nfc(k) for k in keys])]
    return [(label, f"{d[key].nunique()}곳", d[date_col].min(), d[date_col].max(), f"{len(d):,}")]


def step_check(a):
    R = research_dir(a)
    R_TMS, R_W = find(R, "data_tms"), find(R, "data_weather")
    say("\n## 현황 (total/ = 연구 범위 원자료 모음, 연구사업 = 분석이 읽는 파일)")
    say("| 자료 | 지점 | 처음 | 마지막 | 행 |")
    say("|---|---|---|---|---|")
    rows = []
    rows += span_rows("total 하천", T(T_RIVER, "data", "data_수질자동측정망.csv"), "측정소", "날짜")
    rows += span_rows("연구사업 하천(범위 4곳)", find(R_TMS, "수질자동측정망_data.csv"), "측정소", "날짜", list(RIVER_SITES.values()))
    tc = T_TMS / "tms_all_clean.csv"
    rows += span_rows("total TMS", tc if tc.exists() else None, "사업장명", "날짜")
    rf = find(R_TMS, "하수폐수측정망_data.csv")
    if rf is not None:
        d = read(rf, usecols=["사업장명", "연도", "분기", "일자"], dtype=str)
        dd = d[d["사업장명"].map(tms_scope)]
        dt = pd.to_datetime(dd["연도"] + dd["일자"], format="%Y%m월%d일", errors="coerce")
        rows.append(("연구사업 TMS(범위)", f"{dd['사업장명'].nunique()}곳", f"{dt.min():%Y-%m-%d}", f"{dt.max():%Y-%m-%d}", f"{len(dd):,}"))
    rows += span_rows("total ASOS", T(T_ASOS, "data", "기상청_ASOS_weather_daily.csv"), "stn", "date")
    rows += span_rows("total 수위·유량", T(T_LEVEL, "data", "홍수통제소_수위유량_일자료.csv"), "obscd", "date")
    rows += span_rows("total 우량계", T(T_LEVEL, "data", "홍수통제소_우량_일자료.csv"), "stn", "date")
    rows += span_rows("연구사업 유량(전체)", find(R_W, "flow_daily.csv"), "obscd", "date")
    rows += span_rows("연구사업 기상(전체)", find(R_W, "weather_daily.csv"), "stn", "date")
    for r in rows:
        say("| " + " | ".join(str(v) for v in r) + " |")
    raw = find(T_TMS, "raw")
    if raw is not None:
        say("\n| total TMS 분기 | 범위 안 사업장(목록) | 받은 파일 | 잠정치(p) 행 |")
        say("|---|---|---|---|")
        for t in sorted(p.name for p in raw.iterdir() if p.is_dir()):
            ns, nf, pv = tms_status(T_TMS, t)
            say(f"| {t} | {ns} | {nf} | {pv:,} |")


def main():
    ap = argparse.ArgumentParser(description="한탄강 연구 범위 통합 수집 → total/ → 연구사업")
    ap.add_argument("--only", nargs="+", choices=["river", "weather", "level"], help="일부만 실행")
    ap.add_argument("--tms", nargs="+", metavar="YYYYQn", default=[], help="방류수 TMS 크롤링할 분기(예: 2026Q4)")
    ap.add_argument("--tms-refresh", action="store_true", help="이미 받은 사업장도 다시(잠정치 → 확정치)")
    ap.add_argument("--tms-show", action="store_true", help="크롤링 브라우저 창 보이기")
    ap.add_argument("--tms-include-open", action="store_true", help="아직 끝나지 않은 분기도 조회(부분 자료)")
    ap.add_argument("--test", action="store_true", help="API 연결만 확인(파일 안 바꿈)")
    ap.add_argument("--merge-only", action="store_true", help="받지 않고 total 결합 + 연구사업 반영만")
    ap.add_argument("--check", action="store_true", help="받지 않고 현황 표만")
    ap.add_argument("--init-total", action="store_true", help="total/ 에 빠진 시드 파일 다시 채우기(+결합)")
    ap.add_argument("--no-research", action="store_true", help="연구사업 폴더는 건드리지 않음")
    ap.add_argument("--research-overwrite", action="store_true", help="연구사업 파일의 겹치는 날짜도 total 값으로 바꿈")
    ap.add_argument("--research", default=None, help="연구사업 폴더 경로(기본: Study 옆의 연구사업)")
    a = ap.parse_args()

    say(f"# 통합 수집 ({datetime.now():%Y-%m-%d %H:%M}) — {SCOPE_NAME}")
    say(f"- 실행: python 통합수집.py {' '.join(sys.argv[1:])}".rstrip())
    try:
        if a.check:
            step_check(a)
            return 0
        if a.init_total or not TOTAL.exists():
            init_total()
            if not a.test:
                say("\n## total/ 결합본 만들기")
                total_river_data()
                total_tms_data()
                a2 = argparse.Namespace(**{**vars(a), "merge_only": True, "test": False})
                step_weather(a2)
                step_level(a2)
            if a.init_total and not (a.only or a.tms or a.merge_only):
                step_check(a)
                return 0
        if a.tms and a.only is None and not a.merge_only:
            say("- --tms 만 주었으므로 하천·기상·수위는 받지 않음(함께 하려면 --only river weather level 추가)")
            steps = []
        else:
            steps = a.only or ["river", "weather", "level"]
        todo = [("river", step_river, "river" in steps),
                ("tms", step_tms, bool(a.tms) or (a.merge_only and a.only is None)),
                ("weather", step_weather, "weather" in steps),
                ("level", step_level, "level" in steps)]
        for name, fn, on in todo:
            if not on:
                continue
            try:
                fn(a)
            except Exception as e:  # 한 자료가 실패해도 나머지는 계속
                say(f"  [!] {name} 단계 실패: {type(e).__name__}: {str(e)[:200]} → 다음 자료로 넘어감")
        if not a.test and not a.no_research:
            step_research(a)
        if not a.test:
            step_check(a)
    finally:
        SUMMARY.write_text("\n".join(LOG) + "\n", encoding="utf-8")
        print(f"\n요약 저장: {SUMMARY.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
