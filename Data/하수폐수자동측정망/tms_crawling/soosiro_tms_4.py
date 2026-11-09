"""
SOOSIRO 수질TMS 사업장별 배출량(일) 크롤러 (Selenium)  -  v4 (장애 자동복구판)

[v4 핵심: '오류가 나도 멈추지 않고, 스스로 복구하고, 이어받을 수 있게']
1) 브라우저 장애 자동복구
   - 페이지 로딩 지연/타임아웃, 크롬 비정상 종료, 알림창, 화면 구조 지연 등을 감지해
     재시도 → 브라우저 재시작 → 브라우저 모드 단계 상승(헤드리스 eager → none → 일반 창)
   - 로딩을 막는 외부 요청(응답 없는 외부 서버)을 찾아 자동 차단하고 진단 내용을 남김
   - 장시간 실행 시 N건마다 브라우저를 새로 시작해 성능 저하 방지
2) 빈 결과 오판 방지
   - 조회 전에 기존 표에 표시를 달고, '표가 새로 그려졌는지'를 확인한 뒤에만 빈 결과로 판단
3) 데이터 안전
   - CSV는 임시파일에 쓴 뒤 교체(저장 중 중단돼도 깨진 파일이 남지 않음)
   - failed.log 중복/줄붙음 방지, 확정 빈 결과는 즉시 저장 → 중단돼도 손실 없음
   - 엑셀 등에서 파일을 열어둬서 저장이 막히면 다른 이름으로 저장
4) 연속 실패가 계속되면(사이트 점검 등) 충돌 없이 깔끔하게 정리 후 종료 → 다시 실행하면 이어받기
5) 저장 위치 고정(이 파일 옆의 data/), 아직 끝나지 않은 분기 자동 건너뜀, 분기 조기 종료

사용 준비:
    pip install selenium pandas lxml
    (Selenium 4.6+ 는 크롬드라이버를 자동으로 받아옵니다. 크롬 브라우저만 설치돼 있으면 됩니다.)

실행 예:
    # 0) 문제가 계속되면 먼저 진단 (브라우저 모드별로 접속 시간을 측정해 run.log 에 기록)
    python soosiro_tms_4.py --diagnose

    # 1) 테스트 (경기도 2025년 1분기, 사업장 3곳만, 브라우저 창 보이게)
    python soosiro_tms_4.py --years 2025 --quarters 1 --limit 3 --show

    # 2) 전체 수집. 중단 후 같은 명령을 다시 실행하면 받은 사업장은 건너뜀
    python soosiro_tms_4.py --years 2024 2025 2026 --quarters 1 2 3 4

    # 3) 수집 없이 병합·정제만
    python soosiro_tms_4.py --merge

결과 (모두 데이터 폴더 아래, 기본은 이 파일 옆의 data/):
    raw/{연도}Q{분기}/{사업장명}.csv   사업장별 원본(문자열 그대로)
    site_list_{연도}Q{분기}.csv       사업장 목록(폐쇄 표시 포함)
    tms_all_raw.csv / tms_all_clean.csv   병합 원본 / 정제본
    failed.log                        빈 결과·오류 기록 (재수집 코드의 입력, 중복 없음)
    confirmed_empty.csv               재조회로 확인된 '진짜 자료 없음' 목록
    skipped_quarters.log              조기 종료로 조회를 생략한 분기 기록
    quarter_errors.log                분기 단위로 끝내 처리하지 못한 기록
    run.log                           실행 기록(시각·오류 원인·진단) - 문제 발생 시 이 파일을 보세요
    debug/                            첫 실행 결과표 HTML, 실패 순간의 진단 스냅샷
"""
import argparse
import collections
import csv
import json
import os
import platform
import random
import re
import shutil
import sys
import time
import unicodedata
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
    JavascriptException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    UnexpectedAlertPresentException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

# ── 환경 설정 (운영 기본값. 시험 시에만 환경변수로 덮어씀) ───────────────
URL = os.environ.get("SOOSIRO_URL", "https://www.soosiro.or.kr/open/web/daily?pMENU_NO=419")
PAGELOAD_TIMEOUT = float(os.environ.get("SOOSIRO_PAGELOAD_TIMEOUT", "45"))  # 페이지 로딩 제한(초)
READY_TIMEOUT = float(os.environ.get("SOOSIRO_READY_TIMEOUT", "45"))        # 조회 화면 대기(초)
QUERY_TIMEOUT = float(os.environ.get("SOOSIRO_QUERY_TIMEOUT", "45"))        # 사업장 조회 결과 대기(초)
TIME_SCALE = float(os.environ.get("SOOSIRO_TIME_SCALE", "1"))               # 휴식시간 배율(시험용)

HANG_SECS = max(3.0, PAGELOAD_TIMEOUT * 0.6)  # 이 시간 넘게 끝나지 않다 취소된 요청 = 막힌 요청
RECYCLE_EVERY = 150    # 이 횟수만큼 조회하면 브라우저를 새로 시작
GIVEUP_STREAK = 10     # 성공 없이 인프라 실패가 이만큼 연속되면 이번 실행을 정리하고 종료
COOLDOWN_STREAK = 5    # 연속 실패가 이 횟수에 이르면 한 번 길게 쉼
MAX_SNAPSHOTS = 4      # 실행당 진단 스냅샷 최대 개수

# ── 조회 조건 XPath ───────────────────────────────────────────────────
XP_YEAR = "/html/body/div[1]/div[3]/div[3]/form[2]/div/dl[1]/dd/ul/li/select"
XP_QUARTER = "/html/body/div[1]/div[3]/div[3]/form[2]/div/dl[2]/dd/select"
XP_REGION = "/html/body/div[1]/div[3]/div[3]/form[2]/div/dl[3]/dd/select"
XP_SITE = "/html/body/div[1]/div[3]/div[3]/form[2]/div/dl[4]/dd[1]/select"
XP_SEARCH = "/html/body/div[1]/div[3]/div[3]/form[2]/div/ul/li[2]/a"

# ── 결과표 XPath ──────────────────────────────────────────────────────
XP_TABLE = "/html/body/div[1]/div[3]/div[3]/form[3]/div[2]/table"
XP_TBODY = XP_TABLE + "/tbody"

# 결과표 컬럼 (헤더가 2단이라 직접 지정). pH는 측정값만, 나머지는 측정값+배출량
COLS = [
    "순번", "연도", "분기", "사업장명", "일자", "방류구",
    "pH_측정값",
    "TOC_측정값", "TOC_배출량",
    "SS_측정값", "SS_배출량",
    "TN_측정값", "TN_배출량",
    "TP_측정값", "TP_배출량",
]
N_COLS = len(COLS)  # 15
VALUE_COLS = COLS[6:]
SKIP_TEXTS = ("선택", "전체", "사업장 선택")

REGION_NAME = "경기도"

# 이 파일이 있는 폴더 기준으로 고정 (실행 위치와 무관)
BASE_DIR = Path(__file__).resolve().parent
OUT = BASE_DIR / "data"
RAW = OUT / "raw"
DEBUG = OUT / "debug"

# 브라우저 모드 단계: 앞 단계에서 계속 타임아웃이 나면 다음 단계로 올라감
PROFILES = [
    {"name": "헤드리스(eager)", "headless": True, "strategy": "eager"},
    {"name": "헤드리스(none)", "headless": True, "strategy": "none"},
    {"name": "일반 창(화면 밖)", "headless": False, "strategy": "eager"},
]

# ── 페이지 안에서 실행하는 JS ────────────────────────────────────────────
JS_SNAPSHOT = """
const tb = document.evaluate(arguments[0], document, null,
    XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
if (!tb) return null;
const trs = Array.from(tb.querySelectorAll('tr'));
return {
  fresh: trs.length > 0 && trs.every(tr => !tr.__old),
  rows: trs.map(tr => Array.from(tr.children).map(td =>
      (td.textContent || '').replace(/\\u00a0/g, ' ').trim()))
};
"""
JS_MARK_OLD = """
const tb = document.evaluate(arguments[0], document, null,
    XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
if (!tb) return false;
tb.querySelectorAll('tr').forEach(tr => { tr.__old = true; });
return true;
"""
JS_READY = """
const el = document.evaluate(arguments[0], document, null,
    XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
return (window.__soosiro_old === undefined) && !!el && !!el.options && el.options.length > 0;
"""
JS_SITE_OPTIONS = """
const el = document.evaluate(arguments[0], document, null,
    XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
if (!el || !el.options) return null;
return Array.from(el.options).map(o => [o.value || '',
    (o.textContent || '').replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim()]);
"""

# 대기 중 무시하고 다시 시도할 일시적 예외
IGNORED = (NoSuchElementException, StaleElementReferenceException, JavascriptException,
           ElementNotInteractableException, ElementClickInterceptedException)


# ══════════════════════════════════════════════════════════════════════
#  예외 종류
# ══════════════════════════════════════════════════════════════════════
class GiveUp(Exception):
    """연속 실패가 계속돼 이번 실행을 정리하고 종료해야 할 때."""


class BrowserUnavailable(Exception):
    """크롬 브라우저 자체를 시작할 수 없을 때."""


class SoftError(Exception):
    """페이지/데이터 수준의 일시 오류 (브라우저 장애가 아니므로 연속 실패로 세지 않음)."""


class ResultMismatch(SoftError):
    """조회 결과가 선택한 사업장의 것이 아님."""


class PageAlert(SoftError):
    """예상 밖의 알림창."""


class RetryNow(SoftError):
    """원인(응답 없는 외부 요청)을 제거했으니 바로 다시 시도."""


# ══════════════════════════════════════════════════════════════════════
#  공통 도구: 출력·파일 저장·로그
# ══════════════════════════════════════════════════════════════════════
def fix_console_encoding():
    """윈도우 콘솔(cp949 등)에서 한글 출력 오류가 나지 않도록 UTF-8로 맞춤."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def nap(sec):
    time.sleep(max(0.0, sec) * TIME_SCALE)


def pause(a=0.6, b=1.4):
    nap(random.uniform(a, b))


def nfc(s):
    return unicodedata.normalize("NFC", s or "")


def safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", s).strip("_")


def norm_site(s: str) -> str:
    """사업장명 비교용 정규화 ([폐쇄] 표시·공백 제거, 한글 조합 방식 통일)."""
    return re.sub(r"\[.*?\]|\s+", "", nfc(s))


def short_err(e, n=160):
    """예외를 한 줄 요약 (셀레니움 메시지는 여러 줄·스택트레이스라 로그가 깨지지 않게)."""
    msg = " ".join(str(e).split())
    msg = msg.split("Stacktrace:")[0]
    msg = re.sub(r"\(Session info:.*?\)", "", msg).strip()
    return f"{type(e).__name__}: {msg[:n]}"


def set_data_dir(path):
    """데이터 폴더 지정 (OUT/RAW/DEBUG 를 함께 바꿈)."""
    global OUT, RAW, DEBUG, _failed_keys
    OUT = Path(path).expanduser().resolve()
    RAW = OUT / "raw"
    DEBUG = OUT / "debug"
    _failed_keys = None
    OUT.mkdir(parents=True, exist_ok=True)


def say(msg=""):
    """화면 출력 + data/run.log 기록. 어떤 경우에도 예외를 내지 않는다."""
    line = str(msg)
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        OUT.mkdir(parents=True, exist_ok=True)
        with open(OUT / "run.log", "a", encoding="utf-8", newline="\n") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {line}\n")
    except Exception:
        pass


def rotate_run_log(limit_mb=5):
    try:
        p = OUT / "run.log"
        if p.exists() and p.stat().st_size > limit_mb * 1024 * 1024:
            os.replace(p, OUT / "run.log.1")
    except Exception:
        pass


def read_lines_auto(path: Path):
    """줄 단위로 utf-8 → cp949 순으로 해석 (편집기·OS가 섞여도 읽힘)."""
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return []
    lines = []
    for b in raw.splitlines():
        for enc in ("utf-8-sig", "cp949"):
            try:
                lines.append(b.decode(enc))
                break
            except UnicodeDecodeError:
                continue
        else:
            lines.append(b.decode("utf-8", errors="replace"))
    return lines


def _ensure_trailing_newline(path: Path):
    """파일 끝에 줄바꿈이 없으면 추가 (다음 기록이 앞 줄에 붙어버리는 것 방지)."""
    try:
        if path.exists() and path.stat().st_size > 0:
            with open(path, "rb+") as f:
                f.seek(-1, os.SEEK_END)
                if f.read(1) not in (b"\n", b"\r"):
                    f.write(b"\n")
    except OSError:
        pass


def append_line(path: Path, line: str):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_trailing_newline(path)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(line.replace("\r", " ").replace("\n", " ") + "\n")


def write_text_atomic(path: Path, text: str):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def save_csv_atomic(df, path):
    """임시파일에 쓴 뒤 교체. 대상 파일이 열려 있어 막히면 시각을 붙인 이름으로 저장."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    try:
        os.replace(tmp, path)
        return path
    except PermissionError:
        alt = path.with_name(f"{path.stem}_{datetime.now():%Y%m%d_%H%M%S}{path.suffix}")
        os.replace(tmp, alt)
        say(f"  [!] {path.name} 이(가) 다른 프로그램(엑셀 등)에서 열려 있어 {alt.name} 로 저장했습니다.")
        return alt


def have_data(tag, name):
    """해당 사업장 CSV가 이미 있는지 (한글 조합 방식이 달라도 찾음)."""
    stem = safe_name(name)
    for form in ("NFC", "NFD"):
        p = RAW / tag / (unicodedata.normalize(form, stem) + ".csv")
        try:
            if p.exists() and p.stat().st_size > 0:
                return True
        except OSError:
            pass
    return False


def cleanup_partial():
    """이전 실행이 중간에 끊겨 남은 임시파일·빈 파일 정리."""
    n = 0
    try:
        for p in list(OUT.glob("*.tmp")) + list(RAW.glob("*/*.tmp")):
            try:
                p.unlink()
                n += 1
            except OSError:
                pass
        for p in RAW.glob("*/*.csv"):
            try:
                if p.stat().st_size == 0:
                    p.unlink()
                    n += 1
            except OSError:
                pass
    except Exception:
        pass
    if n:
        say(f"[정리] 이전 실행에서 남은 임시/빈 파일 {n}개를 정리했습니다.")


# ── failed.log 처리 ─────────────────────────────────────────────────
LOG_LINE = re.compile(r"^\s*(\d{4})Q([1-4])\s*\|\s*(.+?)\s*\|\s*(.*?)\s*$")
GLUED = re.compile(r"(?<=\S)(?=\d{4}Q[1-4]\s*\|)")
_failed_keys = None


def read_failed_log(path: Path):
    """failed.log → [(year, quarter, site, reason)] (중복 제거·순서 유지·줄붙음 분리)."""
    seen, items = set(), []
    for line in read_lines_auto(path):
        for part in GLUED.split(line):
            m = LOG_LINE.match(part)
            if not m:
                continue
            year, q, name, reason = int(m[1]), int(m[2]), nfc(m[3]), m[4]
            key = (year, q, name)
            if key in seen:
                continue
            seen.add(key)
            items.append((year, q, name, reason))
    return items


def log_fail(msg: str):
    """failed.log 에 기록 (같은 분기·사업장은 한 번만)."""
    global _failed_keys
    msg = msg.replace("\r", " ").replace("\n", " ")
    m = LOG_LINE.match(msg)
    if m:
        if _failed_keys is None:
            _failed_keys = {(f"{y}Q{q}", n) for y, q, n, _ in read_failed_log(OUT / "failed.log")}
        key = (f"{m[1]}Q{m[2]}", nfc(m[3]))
        if key in _failed_keys:
            say(f"  [!] {msg}  (이미 기록된 건)")
            return
        _failed_keys.add(key)
    append_line(OUT / "failed.log", msg)
    say("  [!] " + msg)


def compact_failed_log(path: Path):
    """해결된 건(복구됨/확정 빈 결과)을 failed.log 에서 제거. 원본은 .bak 으로 보관."""
    path = Path(path)
    entries = read_failed_log(path)
    confirmed = load_confirmed()
    keep = []
    for year, q, name, reason in entries:
        tag = f"{year}Q{q}"
        if have_data(tag, name) or (tag, name) in confirmed:
            continue
        keep.append(f"{tag} | {name} | {reason}")
    shutil.copy2(path, path.with_name(path.name + ".bak"))
    write_text_atomic(path, "\n".join(keep) + ("\n" if keep else ""))
    global _failed_keys
    _failed_keys = None
    return len(entries), len(keep)


# ── confirmed_empty.csv (재조회로 확인된 '진짜 자료 없음') ─────────────
def load_confirmed():
    p = OUT / "confirmed_empty.csv"
    out = set()
    try:
        for i, row in enumerate(csv.reader(read_lines_auto(p))):
            if len(row) >= 2 and not (i == 0 and row[0].strip() == "quarter"):
                out.add((row[0].strip(), nfc(row[1].strip())))
    except Exception:
        pass
    return out


def add_confirmed(tag, name):
    p = OUT / "confirmed_empty.csv"
    new = (not p.exists()) or p.stat().st_size == 0
    _ensure_trailing_newline(p)
    with open(p, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        if new:
            w.writerow(["quarter", "site_name"])
        w.writerow([tag, name])


# ── 분기 건너뛰기 ───────────────────────────────────────────────────
def quarter_end(year: int, q: int) -> date:
    """해당 분기의 마지막 날."""
    first_next = date(year + (q == 4), 1 if q == 4 else q * 3 + 1, 1)
    return first_next - timedelta(days=1)


def is_open_quarter(year: int, q: int, lag_days: int = 0) -> bool:
    """아직 끝나지 않은(= 자료가 있을 수 없는) 분기인지. lag_days: 종료 후 자료 반영 지연일."""
    return date.today() <= quarter_end(year, q) + timedelta(days=lag_days)


# ── 사이트 접속 점검 (참고용, 실패해도 중단하지 않음) ───────────────────
def probe_site(timeout=20):
    """브라우저 없이 사이트가 응답하는지 확인. (상태코드, 소요초) 또는 (None, 예외)."""
    import ssl
    err = None
    for ctx in (None, ssl._create_unverified_context()):  # 맥 파이썬의 인증서 문제 대비(접속 확인 전용)
        try:
            t0 = time.time()
            req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                r.read(2048)
                return r.status, time.time() - t0
        except Exception as e:
            err = e
    return None, err


# ══════════════════════════════════════════════════════════════════════
#  브라우저 생성
# ══════════════════════════════════════════════════════════════════════
def build_options(profile, show=False, images=False, minimal=False):
    opt = Options()
    headless = profile["headless"] and not show
    if headless:
        opt.add_argument("--headless=new")
    opt.add_argument("--window-size=1400,1000")
    opt.add_argument("--lang=ko-KR")
    opt.page_load_strategy = profile["strategy"]
    if not show and not profile["headless"]:
        opt.add_argument("--window-position=-32000,-32000")  # 창을 화면 밖으로
    if platform.system() == "Linux":
        opt.add_argument("--no-sandbox")
        opt.add_argument("--disable-dev-shm-usage")
    if not minimal:
        for a in ("--disable-gpu", "--disable-extensions", "--disable-notifications",
                  "--no-first-run", "--no-default-browser-check", "--mute-audio",
                  "--disable-blink-features=AutomationControlled",
                  "--disable-background-timer-throttling",
                  "--disable-renderer-backgrounding",
                  "--disable-backgrounding-occluded-windows"):
            opt.add_argument(a)
        opt.add_experimental_option("excludeSwitches", ["enable-automation"])
        prefs = {"profile.default_content_setting_values.notifications": 2}
        if not images:
            prefs["profile.managed_default_content_settings.images"] = 2  # 이미지는 자료와 무관 → 로딩 단축
        opt.add_experimental_option("prefs", prefs)
        opt.set_capability("goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"})
    return opt


def make_driver(profile, show=False, images=False, minimal=False):
    path = os.environ.get("SOOSIRO_CHROMEDRIVER")  # 시험용: 드라이버 경로 직접 지정
    service = Service(executable_path=path) if path else None
    drv = webdriver.Chrome(options=build_options(profile, show, images, minimal), service=service)
    drv.set_page_load_timeout(PAGELOAD_TIMEOUT)
    drv.set_script_timeout(30)
    if not minimal:
        try:  # 헤드리스 표식을 일반 크롬처럼 보이게
            ua = drv.execute_cdp_cmd("Browser.getVersion", {}).get("userAgent", "")
            if "Headless" in ua:
                drv.execute_cdp_cmd("Network.setUserAgentOverride",
                                    {"userAgent": ua.replace("HeadlessChrome", "Chrome")})
        except Exception:
            pass
    return drv


# ── 오류 성격 판별 ──────────────────────────────────────────────────
DEAD_HINTS = ("invalid session id", "session deleted", "not reachable", "disconnected",
              "no such window", "target window already closed", "web view not found",
              "chrome failed to start", "crashed", "maxretryerror", "connection aborted",
              "remotedisconnected", "connectionreseterror", "cannot connect to chrome",
              "devtoolsactiveport", "connection refused", "newconnectionerror")


def is_timeout(e):
    s = str(e).lower()
    return isinstance(e, TimeoutException) or "timed out" in s or "timeout" in s


def is_dead(e):
    s = (type(e).__name__ + " " + str(e)).lower()
    return any(h in s for h in DEAD_HINTS)


Fetch = collections.namedtuple("Fetch", "status df detail verified")


# ══════════════════════════════════════════════════════════════════════
#  Session : 브라우저 1개를 감싸고 장애를 스스로 복구
# ══════════════════════════════════════════════════════════════════════
class Session:
    def __init__(self, show=False, images=False, level=0):
        self.show = show
        self.images = images
        self.max_level = 1 if show else len(PROFILES) - 1
        self.level = min(level, self.max_level)
        self.drv = None
        self.streak = 0           # 성공 없이 이어진 인프라 실패 횟수
        self.timeout_streak = 0   # 타임아웃이 이어진 횟수 (모드 상승 판단)
        self.queries = 0
        self.snaps = 0
        self.restarts = 0
        self.blocked = set()      # 응답 없는 외부 호스트(자동 차단)
        self.last_alert = None
        self.start()

    # ── 시작/종료 ───────────────────────────────────────────────────
    def start(self):
        """현재 모드로 브라우저 시작. 올라간 모드가 이 컴퓨터에서 시작되지 않으면 한 단계씩 내려가
        동작하는 모드로 계속한다(예: 화면이 없는 환경에서 '일반 창' 모드 불가)."""
        self.stop()
        last = None
        for lvl in range(self.level, -1, -1):
            prof = PROFILES[lvl]
            tries = 3 if lvl == 0 else 2
            for i in range(1, tries + 1):
                try:
                    self.drv = make_driver(prof, self.show, self.images, minimal=(i >= 2))
                    if lvl != self.level:
                        say(f"  [!] 모드 '{PROFILES[self.level]['name']}' 를 시작할 수 없어 "
                            f"'{prof['name']}' 로 계속합니다.")
                        self.level = lvl
                        self.max_level = min(self.max_level, lvl)
                    self.apply_blocks()
                    say(f"  [브라우저 시작] 모드: {prof['name']}")
                    return
                except Exception as e:
                    last = e
                    say(f"  [브라우저 시작 실패 {prof['name']} {i}/{tries}] {short_err(e)}")
                    self.stop()
                    nap(3 * i)
        raise BrowserUnavailable(
            "크롬 브라우저를 시작하지 못했습니다. 크롬이 설치돼 있는지, 크롬을 최근에 업데이트했다면 "
            "컴퓨터를 한 번 재시작한 뒤 다시 실행해 보세요. 마지막 오류: " + short_err(last, 200))

    def stop(self):
        drv, self.drv = self.drv, None
        if drv is not None:
            try:
                drv.quit()
            except Exception:
                pass

    def restart(self, escalate=False, reason=""):
        if escalate and self.level < self.max_level:
            self.level += 1
        self.restarts += 1
        self.queries = 0
        say(f"  [브라우저 재시작] {reason} → 모드: {PROFILES[self.level]['name']}")
        self.start()

    def should_recycle(self):
        return self.queries >= RECYCLE_EVERY

    # ── 실패/성공 기록과 복구 ───────────────────────────────────────
    def ok(self):
        self.streak = 0
        self.timeout_streak = 0

    def fail(self, e, what, attempt, tries):
        """실패 1건 처리: 기록·진단·(필요 시) 브라우저 재시작·대기. 연속 실패가 한계면 GiveUp."""
        if isinstance(e, RetryNow):
            say(f"  [재시도 {attempt}/{tries}] {what}: {e}")
            return
        soft = isinstance(e, SoftError)
        if not soft:
            self.streak += 1
            self.timeout_streak = self.timeout_streak + 1 if is_timeout(e) else 0
        say(f"  [재시도 {attempt}/{tries}] {what}: {short_err(e)}")
        self.dismiss_alert()
        self.snapshot(what, e)
        if self.streak >= GIVEUP_STREAK:
            raise GiveUp(f"성공 없이 오류가 {self.streak}회 연속됐습니다 (마지막: {short_err(e, 120)})")
        if self.streak == COOLDOWN_STREAK:
            say("  [!] 연속 실패 → 사이트/네트워크가 불안정한 것 같아 90초 쉬었다가 계속합니다.")
            nap(90)
        if attempt < tries:
            if attempt >= 2 or is_dead(e):
                self.restart(escalate=(not soft and self.timeout_streak >= 2),
                             reason="오류 복구" if not is_dead(e) else "브라우저 비정상 종료 복구")
            nap(min(45, 3 * attempt))

    # ── 알림창/로그/진단 ────────────────────────────────────────────
    def note_alert(self, e):
        self.last_alert = getattr(e, "alert_text", None) or str(e)
        self.dismiss_alert()

    def dismiss_alert(self):
        if self.drv is None:
            return
        for _ in range(3):
            try:
                self.drv.switch_to.alert.accept()
            except Exception:
                break

    def pending_requests(self):
        """직전 구간 네트워크 로그에서 '요청은 보냈지만 끝나지 않은' URL 목록."""
        try:
            entries = self.drv.get_log("performance")
        except Exception:
            return []
        pend, starts, hung = {}, {}, []
        for en in entries:
            try:
                m = json.loads(en["message"])["message"]
            except Exception:
                continue
            method, p = m.get("method", ""), (m.get("params") or {})
            rid = p.get("requestId")
            if method == "Network.requestWillBeSent":
                url = (p.get("request") or {}).get("url", "")
                if url.startswith("http"):
                    pend[rid] = url
                    starts[rid] = p.get("timestamp")
            elif method == "Network.loadingFinished":
                pend.pop(rid, None)
            elif method == "Network.loadingFailed":
                url = pend.pop(rid, None)
                t0, t1 = starts.get(rid), p.get("timestamp")
                # 로딩 제한시간에 걸려 브라우저가 대신 취소한 요청도 '막힌 요청'으로 본다
                if (url and p.get("canceled") and t0 is not None and t1 is not None
                        and (t1 - t0) >= HANG_SECS):
                    hung.append(url)
        return list(pend.values()) + hung

    def console_lines(self, n=20):
        try:
            return [f"{e.get('level')}: {e.get('message', '')[:200]}"
                    for e in self.drv.get_log("browser")[-n:]]
        except Exception:
            return []

    def diagnose_pending(self):
        """로딩이 끝나지 않은 요청을 기록하고, 응답 없는 외부 호스트는 차단. 새로 차단했으면 True."""
        urls = self.pending_requests()
        if not urls:
            return False
        say("  [진단] 응답이 끝나지 않은 요청: " + " | ".join(sorted({u[:100] for u in urls})[:5]))
        main_host = (urlparse(URL).hostname or "").lower()
        hosts = {(urlparse(u).hostname or "").lower() for u in urls}
        ext = {h for h in hosts
               if h and h != main_host and not h.endswith("soosiro.or.kr")} - self.blocked
        if not ext:
            return False
        self.blocked |= ext
        say("  [자동 차단] 응답 없는 외부 서버를 차단하고 다시 시도합니다: " + ", ".join(sorted(ext)))
        self.apply_blocks()
        return True

    def apply_blocks(self):
        if not self.blocked or self.drv is None:
            return
        pats = []
        for h in sorted(self.blocked):
            pats += [f"*://{h}/*", f"*://{h}:*/*"]  # 기본 포트 / 포트가 붙은 주소 모두
        try:
            self.drv.execute_cdp_cmd("Network.enable", {})
            try:
                self.drv.execute_cdp_cmd("Network.setBlockedURLs", {
                    "urlPatterns": [{"urlPattern": p, "block": True} for p in pats]})
            except Exception:
                self.drv.execute_cdp_cmd("Network.setBlockedURLs", {"urls": pats})
        except Exception as e:
            say(f"  [!] 외부 요청 차단 설정 실패(무시하고 계속): {short_err(e, 100)}")

    def snapshot(self, what, e):
        """실패 순간의 상태(URL·콘솔·화면)를 data/debug 에 남김. 브라우저가 멎었으면 텍스트만."""
        if self.snaps >= MAX_SNAPSHOTS or self.drv is None:
            return
        self.snaps += 1
        try:
            DEBUG.mkdir(parents=True, exist_ok=True)
            stem = DEBUG / f"fail_{datetime.now():%Y%m%d_%H%M%S}_{self.snaps}"
            lines = [f"작업: {what}", f"오류: {short_err(e, 500)}",
                     f"브라우저 모드: {PROFILES[self.level]['name']}",
                     f"차단한 외부 서버: {sorted(self.blocked)}"]
            if not is_timeout(e) and not is_dead(e):
                try:
                    lines.append("URL: " + self.drv.current_url)
                    stem.with_suffix(".html").write_text(self.drv.page_source, encoding="utf-8")
                    self.drv.save_screenshot(str(stem.with_suffix(".png")))
                except Exception:
                    pass
            lines += ["[브라우저 콘솔]"] + self.console_lines()
            lines += ["[응답 없는 요청]"] + self.pending_requests()
            stem.with_suffix(".txt").write_text("\n".join(lines), encoding="utf-8")
            say(f"  [진단 저장] {stem.with_suffix('.txt')}")
        except Exception:
            pass

    # ── 대기 도구 ───────────────────────────────────────────────────
    def wait_until(self, fn, timeout, interval=0.5, desc="조건"):
        t0 = time.time()
        last = None
        while True:
            try:
                v = fn()
                if v:
                    return v
            except UnexpectedAlertPresentException as e:
                self.note_alert(e)
            except IGNORED as e:
                last = e
            if time.time() - t0 >= timeout:
                raise TimeoutException(
                    f"{desc} 대기 시간 초과({timeout:.0f}초)"
                    + (f" / 마지막 오류: {short_err(last, 100)}" if last else ""))
            time.sleep(interval)

    # ── 화면 조작 ───────────────────────────────────────────────────
    def open_page(self):
        drv = self.drv
        for kind in ("performance", "browser"):  # 이전 구간 로그 비우기
            try:
                drv.get_log(kind)
            except Exception:
                pass
        try:
            drv.execute_script("window.__soosiro_old = 1;")  # 이전 문서 표시 → 새 문서 도착 판별용
        except Exception:
            pass
        try:
            try:
                drv.get(URL)
            except UnexpectedAlertPresentException:
                self.dismiss_alert()
                drv.get(URL)
        except TimeoutException:
            blocked_now = self.diagnose_pending()
            try:
                drv.execute_script("window.stop();")
            except Exception:
                pass
            if blocked_now:
                raise RetryNow("응답 없는 외부 서버 차단 후 다시 접속")
        try:
            self.wait_until(lambda: drv.execute_script(JS_READY, XP_YEAR), READY_TIMEOUT,
                            desc="조회 화면 로딩")
        except TimeoutException:
            if self.diagnose_pending():
                raise RetryNow("응답 없는 외부 서버 차단 후 다시 접속")
            raise

    def select_text(self, xpath, key, timeout=25):
        def f():
            sel = Select(self.drv.find_element(By.XPATH, xpath))
            for i, o in enumerate(sel.options):
                if key in o.text:
                    sel.select_by_index(i)
                    return o.text or key
            return None
        return self.wait_until(f, timeout, desc=f"'{key}' 선택")

    def site_options(self):
        """사업장 select 의 (value, text) 목록. 안내용 옵션은 제외. (JS 1회 호출)"""
        raw = self.drv.execute_script(JS_SITE_OPTIONS, XP_SITE)
        if raw is None:
            raise NoSuchElementException("사업장 선택 상자를 찾지 못함")
        return [(v, nfc(t)) for v, t in raw if v and t and t not in SKIP_TEXTS]

    def wait_site_list(self, timeout=40):
        """지역 선택 후 사업장 목록이 채워지고 '두 번 연속 같을 때'까지 대기 (이전 목록 오인 방지)."""
        st = {"prev": None, "same": 0}

        def f():
            cur = self.site_options()
            if not cur:
                st["prev"], st["same"] = None, 0
                return False
            if cur == st["prev"]:
                st["same"] += 1
            else:
                st["prev"], st["same"] = cur, 0
            return cur if st["same"] >= 2 else False
        return self.wait_until(f, timeout, interval=0.6, desc="사업장 목록")

    def open_quarter(self, year, quarter, tries=4):
        """분기 조회 화면 설정 + 사업장 목록 반환 (실패 시 재시도·브라우저 재시작)."""
        last = None
        for i in range(1, tries + 1):
            try:
                self.open_page()
                self.select_text(XP_YEAR, str(year))
                self.select_text(XP_QUARTER, f"{quarter}분기")
                self.select_text(XP_REGION, REGION_NAME)
                pause()
                opts = self.wait_site_list()
                self.ok()
                return opts
            except GiveUp:
                raise
            except Exception as e:
                last = e
                self.fail(e, f"{year}Q{quarter} 화면 설정", i, tries)
        raise last

    def click_search(self):
        btn = self.drv.find_element(By.XPATH, XP_SEARCH)
        try:
            self.drv.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        except Exception:
            pass
        try:
            btn.click()
        except UnexpectedAlertPresentException:
            raise
        except Exception:
            self.drv.execute_script("arguments[0].click();", btn)  # 가려진 경우 대비

    def read_snapshot(self):
        try:
            return self.drv.execute_script(JS_SNAPSHOT, XP_TBODY)
        except UnexpectedAlertPresentException as e:
            self.note_alert(e)
            return None
        except (JavascriptException, StaleElementReferenceException):
            return None

    def wait_result(self, site, timeout=45, min_wait=2.5):
        """조회 결과 대기. 반환 (rows, verified).
        - 데이터 행의 사업장명이 선택한 사업장과 일치 → 즉시 (rows, True)
        - '조회 전 표'가 새로 그려진 뒤 '자료 없음'이 min_wait 초 유지 → (rows, True)  [확인된 빈 결과]
        - 새로 그려진 신호를 못 봤어도 일정 시간이 지나면 (rows, False)  [미확인 빈 결과]
        """
        want = norm_site(site)
        t0 = time.time()
        empty_since = None
        last_rows = None
        soft_limit = min(timeout, 3 * min_wait + 4)
        while True:
            el = time.time() - t0
            if el >= timeout:
                return last_rows, False
            snap = self.read_snapshot()
            if self.last_alert:
                if "없" in self.last_alert:       # '조회된 자료가 없습니다' 류 알림 = 확인된 빈 결과
                    return None, True
                raise PageAlert(f"예상 밖의 알림창: {self.last_alert[:80]}")
            if snap:
                rows = snap["rows"]
                last_rows = rows
                data = [r for r in rows if len(r) >= N_COLS]
                if data:
                    got = norm_site(data[0][3])
                    if got == want or want in got or got in want:
                        return rows, True
                    empty_since = None
                    if snap["fresh"]:                # 표가 새로 그려졌는데 다른 사업장 자료 → 기다려도 소용없음
                        return rows, False           #   (호출부가 '결과 사업장 불일치'로 처리)
                    # 이전 사업장의 표가 아직 남아 있음 → 계속 대기
                elif snap["fresh"]:
                    if empty_since is None:
                        empty_since = time.time()
                    if time.time() - empty_since >= min_wait:
                        return rows, True
                else:
                    empty_since = None
                    if el >= soft_limit:
                        return rows, False
            else:
                empty_since = None
            time.sleep(0.4)

    def query_site(self, name, val, min_wait=2.5, timeout=45):
        """현재 열린 분기 화면에서 사업장 1곳 조회 → (DataFrame | None, 확인여부)."""
        drv = self.drv
        self.wait_until(lambda: (Select(drv.find_element(By.XPATH, XP_SITE)).select_by_value(val) or True),
                        20, desc="사업장 선택")
        pause(0.3, 0.8)
        drv.execute_script(JS_MARK_OLD, XP_TBODY)
        self.last_alert = None
        self.click_search()
        rows, verified = self.wait_result(name, timeout, min_wait)
        pause(0.3, 0.8)
        if is_empty_rows(rows):
            return None, verified
        df = rows_to_df(rows)
        got = {norm_site(s) for s in df["사업장명"].unique()}
        want = norm_site(name)
        if not any(want in g or g in want for g in got):
            raise ResultMismatch(f"결과 사업장 불일치: {sorted(got)[:3]}")
        return df, True

    def dump_debug(self, tag):
        """첫 결과표 HTML 보관 (구조 확인용). 실패해도 무시."""
        try:
            p = DEBUG / f"{tag}_table.html"
            if p.exists():
                return
            DEBUG.mkdir(parents=True, exist_ok=True)
            html = self.drv.find_element(By.XPATH, XP_TABLE).get_attribute("outerHTML")
            p.write_text(html, encoding="utf-8")
        except Exception:
            pass


def is_empty_rows(rows):
    """'자료가 없습니다' 안내 행(셀 1개)이거나 데이터 행이 없는 경우."""
    if not rows:
        return True
    return len([r for r in rows if len(r) >= N_COLS]) == 0


def rows_to_df(rows):
    data = [r[:N_COLS] for r in rows if len(r) >= N_COLS]
    return pd.DataFrame(data, columns=COLS)


# ══════════════════════════════════════════════════════════════════════
#  QuarterCtx : 분기 화면 + 사업장 1곳 조회(장애 복구 포함)
# ══════════════════════════════════════════════════════════════════════
class QuarterCtx:
    def __init__(self, sess, year, quarter):
        self.sess, self.year, self.q = sess, year, quarter
        self.tag = f"{year}Q{quarter}"
        self.opts, self.by_text, self.by_norm = [], {}, {}

    def open(self):
        self.opts = self.sess.open_quarter(self.year, self.q)
        self.by_text = {t: v for v, t in self.opts}
        self.by_norm = {norm_site(t): v for v, t in self.opts}
        return self.opts

    def val_of(self, name):
        name = nfc(name)
        return self.by_text.get(name) or self.by_norm.get(norm_site(name))

    def fetch(self, name, waits=(2.5,), timeout=None, max_err=4):
        """사업장 1곳 조회. waits 개수만큼 '빈 결과'가 확인돼야 empty 로 확정(2번째부터는 화면을 새로 열어 재조회).
        반환 Fetch(status, df, detail, verified)
          status: data | empty | error | missing(사업장 목록에 없음)"""
        sess = self.sess
        timeout = timeout or QUERY_TIMEOUT
        errs = empties = 0
        need_open = False
        all_verified = True
        while True:
            try:
                if sess.should_recycle():
                    sess.restart(reason="정기 재시작(장시간 실행 안정화)")
                    need_open = True
                if need_open or empties > 0:
                    self.open()
                    need_open = False
                val = self.val_of(name)
                if not val:
                    return Fetch("missing", None, "사업장 목록에 없음", False)
                min_wait = waits[min(empties, len(waits) - 1)]
                df, verified = sess.query_site(name, val, min_wait, timeout)
                sess.ok()
                sess.queries += 1
                if df is not None:
                    return Fetch("data", df, f"{len(df)}행", True)
                empties += 1
                all_verified = all_verified and verified
                if empties >= len(waits):
                    return Fetch("empty", None, f"{empties}회 조회 모두 자료 없음", all_verified)
            except GiveUp:
                raise
            except Exception as e:
                errs += 1
                sess.fail(e, f"{self.tag} {name}", errs, max_err)
                if errs >= max_err:
                    return Fetch("error", None, short_err(e), False)
                need_open = True


# ══════════════════════════════════════════════════════════════════════
#  수집
# ══════════════════════════════════════════════════════════════════════
def crawl_quarter(sess, year, quarter, limit=None, early_exit=10, recheck_empty=False):
    """early_exit: 폐쇄 표시가 없는 사업장이 앞에서부터 N곳 '확인된 빈 결과'이고
    자료가 있는 곳이 한 곳도 없으면 그 분기의 나머지는 조회하지 않음 (0이면 끔)."""
    tag = f"{year}Q{quarter}"
    outdir = RAW / tag
    outdir.mkdir(parents=True, exist_ok=True)

    ctx = QuarterCtx(sess, year, quarter)
    sites = ctx.open()
    sl = pd.DataFrame(sites, columns=["value", "site_name"])
    sl["closed"] = sl.site_name.str.contains("폐쇄")
    save_csv_atomic(sl, OUT / f"site_list_{tag}.csv")
    say(f"[{tag}] 사업장 {len(sites)}곳")

    confirmed = load_confirmed()
    probe_empty = probe_hit = 0
    for n, (val, name) in enumerate(sites, 1):
        if limit and n > limit:
            break

        if early_exit and probe_hit == 0 and probe_empty >= early_exit:
            rest = len(sites) - n + 1
            msg = f"{tag} | 앞쪽 {early_exit}곳 모두 자료 없음 → 나머지 {rest}곳 조회 생략"
            append_line(OUT / "skipped_quarters.log", msg)
            say("  [건너뜀] " + msg)
            break

        if have_data(tag, name):
            probe_hit += 1  # 이어받기
            continue
        if (tag, name) in confirmed and not recheck_empty:
            continue  # 이미 '진짜 자료 없음'으로 확인된 건

        say(f"[{tag}] ({n}/{len(sites)}) {name}")
        r = ctx.fetch(name, waits=(2.5,))
        if r.status == "data":
            save_csv_atomic(r.df, outdir / f"{safe_name(name)}.csv")
            sess.dump_debug(tag)
            probe_hit += 1
            say(f"      → {r.detail} 저장")
        elif r.status == "empty":
            log_fail(f"{tag} | {name} | 빈 결과(자료 없음)")
            if "폐쇄" not in name and r.verified:
                probe_empty += 1
        else:
            log_fail(f"{tag} | {name} | 오류 {r.detail}")
        pause()  # 서버 부담을 줄이기 위한 대기


def merge_all():
    """사업장별 CSV 병합 → tms_all_raw.csv, 정제본 → tms_all_clean.csv (일부 파일이 깨져도 계속)"""
    files = sorted(RAW.glob("*/*.csv"))
    if not files:
        say("합칠 파일이 없습니다.")
        return
    frames, bad = [], []
    for f in files:
        try:
            frames.append(pd.read_csv(f, dtype=str, encoding="utf-8-sig"))
        except Exception:
            bad.append(f.name)
    if bad:
        say(f"  [!] 읽지 못한 파일 {len(bad)}개는 병합에서 제외: {bad[:5]}")
    if not frames:
        say("병합할 수 있는 파일이 없습니다.")
        return
    df = pd.concat(frames, ignore_index=True)
    out_raw = save_csv_atomic(df, OUT / "tms_all_raw.csv")
    say(f"병합 완료: {len(frames)}개 파일, {len(df):,}행 → {out_raw}")

    try:  # 정제: 잠정치(p) 표시 분리, 숫자 변환, 날짜 생성
        clean = df.copy()
        prov = pd.Series(False, index=clean.index)
        for c in VALUE_COLS:
            if c not in clean.columns:
                continue
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
        out_clean = save_csv_atomic(clean, OUT / "tms_all_clean.csv")
        say(f"정제본 저장 → {out_clean} (잠정치 포함 행 {int(prov.sum()):,})")
    except Exception as e:
        say(f"  [!] 정제본 생성 중 문제가 생겼지만 원본 병합은 완료됐습니다: {short_err(e)}")


def diagnose():
    """브라우저 모드별로 조회 화면 접속을 시험하고 결과를 run.log 에 남김."""
    say("=== 진단 시작 ===")
    st, info = probe_site()
    say(f"[사이트 직접 접속] " + (f"HTTP {st}, {info:.1f}초" if st else f"실패: {short_err(info)}"))
    for lvl, prof in enumerate(PROFILES):
        say(f"--- 브라우저 모드 {lvl}: {prof['name']} ---")
        sess, t0 = None, time.time()
        try:
            sess = Session(show=False, images=False, level=lvl)
            opts = sess.open_quarter(2025, 1, tries=1)
            say(f"  성공: 사업장 {len(opts)}곳 / {time.time() - t0:.1f}초")
        except Exception as e:
            say(f"  실패: {short_err(e, 300)} / {time.time() - t0:.1f}초")
        finally:
            if sess:
                sess.stop()
    say("=== 진단 끝 (run.log 와 data/debug/ 를 확인하세요) ===")


def main():
    fix_console_encoding()
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="+", type=int, default=[2024, 2025, 2026])
    ap.add_argument("--quarters", nargs="+", type=int, default=[1, 2, 3, 4])
    ap.add_argument("--limit", type=int, default=None, help="분기당 최대 사업장 수(테스트용)")
    ap.add_argument("--show", action="store_true", help="브라우저 창 표시")
    ap.add_argument("--merge", action="store_true", help="수집 없이 병합·정제만")
    ap.add_argument("--diagnose", action="store_true", help="브라우저 모드별 접속 진단")
    ap.add_argument("--data-dir", default=None,
                    help="데이터 폴더 (기본: 이 파일 옆의 data/). 동기화 폴더 등 지정 가능")
    ap.add_argument("--skip-quarters", nargs="*", default=[], metavar="YYYYQn",
                    help="조회하지 않을 분기 (예: --skip-quarters 2026Q4 2025Q1)")
    ap.add_argument("--include-open", action="store_true",
                    help="아직 끝나지 않은 분기도 조회 (기본: 자동으로 건너뜀)")
    ap.add_argument("--lag-days", type=int, default=0,
                    help="분기 종료 후 자료 반영까지 기다릴 일수 (기본 0)")
    ap.add_argument("--early-exit", type=int, default=10, metavar="N",
                    help="분기 앞쪽 N곳(폐쇄 제외)이 모두 '자료 없음'이면 나머지 조회 생략 "
                         "(기본 10, 0이면 끔)")
    ap.add_argument("--recheck-empty", action="store_true",
                    help="이미 '진짜 자료 없음'으로 확인된 사업장도 다시 조회")
    ap.add_argument("--with-images", action="store_true", help="이미지 로딩 허용 (기본: 차단해 속도 향상)")
    ap.add_argument("--level", type=int, default=0, choices=range(len(PROFILES)),
                    help="브라우저 모드 시작 단계 (0=헤드리스 eager, 1=헤드리스 none, 2=일반 창)")
    a = ap.parse_args()

    if a.data_dir:
        set_data_dir(a.data_dir)
    OUT.mkdir(parents=True, exist_ok=True)
    rotate_run_log()
    say(f"[환경] {platform.system()} / {platform.node()}   [데이터 폴더] {OUT}")

    if a.diagnose:
        diagnose()
        return
    cleanup_partial()
    if a.merge:
        merge_all()
        return

    st, info = probe_site()
    say("[사이트 점검] " + (f"HTTP {st}, 응답 {info:.1f}초" if st
                           else f"직접 접속 실패({short_err(info, 80)}) → 브라우저로 계속 시도합니다"))

    skip_set = {s.upper() for s in a.skip_quarters}
    sess = None
    stopped = ""
    try:
        sess = Session(show=a.show, images=a.with_images, level=a.level)
        for y in a.years:
            for q in a.quarters:
                tag = f"{y}Q{q}"
                if tag in skip_set:
                    say(f"[건너뜀] {tag}: 제외 지정")
                    continue
                if not a.include_open and is_open_quarter(y, q, a.lag_days):
                    say(f"[건너뜀] {tag}: 아직 끝나지 않은 분기 "
                        f"(종료 {quarter_end(y, q)}, --include-open 으로 해제)")
                    continue
                try:
                    crawl_quarter(sess, y, q, a.limit, a.early_exit, a.recheck_empty)
                except (GiveUp, BrowserUnavailable):
                    raise
                except Exception as e:  # 분기 하나가 실패해도 다음 분기로 계속
                    say(f"[{tag}] 분기 처리 실패: {short_err(e)} → 다음 분기로 넘어갑니다")
                    append_line(OUT / "quarter_errors.log", f"{tag} | {short_err(e)}")
    except GiveUp as e:
        stopped = f"[중단] {e}. 사이트 점검이나 네트워크 문제일 수 있습니다. 잠시 뒤 같은 명령을 다시 실행하면 이어서 받습니다."
    except BrowserUnavailable as e:
        stopped = f"[중단] {e}"
    except KeyboardInterrupt:
        stopped = "[중단] 사용자가 중단했습니다. 지금까지 받은 자료는 저장돼 있어 다시 실행하면 이어서 받습니다."
    finally:
        if sess:
            sess.stop()
    if stopped:
        say(stopped)
    try:
        merge_all()
    except Exception as e:
        say(f"  [!] 병합 중 문제: {short_err(e)} (python soosiro_tms_4.py --merge 로 다시 시도 가능)")


if __name__ == "__main__":
    main()
