"""
SOOSIRO 수질TMS 사업장별 배출량(일) 크롤러 (Selenium)  -  v2.1 (경로 고정 + 자료 없는 분기 건너뛰기)

[v2.1 개선 사항]
1) 저장 위치 고정: 어디서 실행하든 이 파일이 있는 폴더의 data/ 에 저장
   (기존: 실행 위치(cwd) 기준이라 프로젝트 최상위 폴더에 data/ 가 생기는 문제)
   --data-dir 로 다른 위치(동기화 폴더 등) 지정 가능
2) 아직 끝나지 않은 분기(예: 2026Q4)는 자동으로 건너뜀 (--include-open 으로 해제)
3) 분기 앞쪽 사업장들이 모두 '자료 없음'이면 그 분기의 나머지는 조회 생략 (--early-exit)
4) 윈도우 콘솔 한글 출력 오류 방지 (인텔 맥/윈도우/맥미니 공용)

사용 준비:
    pip install selenium pandas lxml
    (Selenium 4.6+ 는 크롬드라이버를 자동으로 받아옵니다. 크롬 브라우저만 설치돼 있으면 됩니다.)

실행 예:
    # 1) 먼저 테스트 (경기도 2025년 1분기, 사업장 3곳만, 브라우저 창 보이게)
    python soosiro_tms_2.py --years 2025 --quarters 1 --limit 3 --show

    # 2) 전체 수집. 중단 후 같은 명령을 다시 실행하면 받은 사업장은 건너뜀
    python soosiro_tms_2.py --years 2024 2025 2026 --quarters 1 2 3 4

    # 특정 분기 제외 / 데이터 폴더 지정
    python soosiro_tms_2.py --skip-quarters 2026Q4 --data-dir "D:/OneDrive/tms_data"

    # 3) 수집 없이 병합·정제만
    python soosiro_tms_2.py --merge

결과 (모두 데이터 폴더 아래, 기본은 이 파일 옆의 data/):
    raw/{연도}Q{분기}/{사업장명}.csv   사업장별 원본(문자열 그대로)
    site_list_{연도}Q{분기}.csv       사업장 목록(폐쇄 표시 포함)
    tms_all_raw.csv                   전체 병합 원본
    tms_all_clean.csv                 숫자 변환 + 날짜 + 잠정치(p) 표시 컬럼
    failed.log                        실패·빈 결과·이상 기록 (재수집 코드의 입력)
    skipped_quarters.log              조기 종료로 조회를 생략한 분기 기록
    debug/                            첫 실행 시 저장하는 결과표 HTML
"""
import argparse
import random
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    UnexpectedAlertPresentException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait

URL = "https://www.soosiro.or.kr/open/web/daily?pMENU_NO=419"

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

REGION_NAME = "경기도"

# 이 파일이 있는 폴더 기준으로 고정 (실행 위치와 무관)
BASE_DIR = Path(__file__).resolve().parent
OUT = BASE_DIR / "data"
RAW = OUT / "raw"
DEBUG = OUT / "debug"

JS_READ_ROWS = """
const xp = arguments[0];
const tb = document.evaluate(xp, document, null,
    XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
if (!tb) return null;
return Array.from(tb.querySelectorAll('tr')).map(tr =>
    Array.from(tr.children).map(td =>
        (td.textContent || '').replace(/\\u00a0/g, ' ').trim()));
"""


def fix_console_encoding():
    """윈도우 콘솔(cp949 등)에서 한글 출력 오류가 나지 않도록 UTF-8로 맞춤."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def pause(a=0.6, b=1.4):
    time.sleep(random.uniform(a, b))


def safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", s).strip("_")


def norm_site(s: str) -> str:
    """사업장명 비교용 정규화 ([폐쇄] 표시·공백 제거)."""
    return re.sub(r"\[.*?\]|\s+", "", s or "")


def log_fail(msg: str):
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "failed.log", "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print("  [!]", msg)


def log_skipped_quarter(msg: str):
    """조기 종료로 생략한 분기 기록 (failed.log 와 분리: 재수집 대상이 아님)."""
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "skipped_quarters.log", "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print("  [건너뜀]", msg)


# ── 분기 건너뛰기 ───────────────────────────────────────────────────
def quarter_end(year: int, q: int) -> date:
    """해당 분기의 마지막 날."""
    first_next = date(year + (q == 4), 1 if q == 4 else q * 3 + 1, 1)
    return first_next - timedelta(days=1)


def is_open_quarter(year: int, q: int, lag_days: int = 0) -> bool:
    """아직 끝나지 않은(= 자료가 있을 수 없는) 분기인지. lag_days: 종료 후 자료 반영 지연일."""
    return date.today() <= quarter_end(year, q) + timedelta(days=lag_days)


def make_driver(show: bool):
    opt = Options()
    if not show:
        opt.add_argument("--headless=new")
    opt.add_argument("--window-size=1400,1000")
    opt.add_argument("--lang=ko-KR")
    # 'eager': 화면 구조(DOM)만 로드되면 바로 진행. 느린 외부 스크립트·이미지를 끝까지
    # 기다리다 "Timed out receiving message from renderer" 오류가 나는 것을 방지
    opt.page_load_strategy = "eager"
    drv = webdriver.Chrome(options=opt)
    drv.set_page_load_timeout(90)
    return drv


def select_by_text(drv, xpath, key, wait=15):
    """옵션 순서(예: 분기가 4→1 역순)에 의존하지 않고, 글자가 포함된 옵션을 선택."""
    el = WebDriverWait(drv, wait).until(lambda d: d.find_element(By.XPATH, xpath))
    sel = Select(el)
    for i, o in enumerate(sel.options):
        if key in o.text:
            sel.select_by_index(i)
            return o.text
    raise NoSuchElementException(f"'{key}' 옵션 없음: {[o.text for o in sel.options]}")


def get_site_options(drv):
    """사업장 select 의 (value, text) 목록. 안내용 첫 옵션(선택 등)은 제외."""
    el = drv.find_element(By.XPATH, XP_SITE)
    out = []
    for o in Select(el).options:
        text = o.text.strip()
        val = o.get_attribute("value")
        if not text or not val or text in ("선택", "전체", "사업장 선택"):
            continue
        out.append((val, text))
    return out


def wait_site_list(drv, timeout=20):
    """지역 선택 후 사업장 목록이 Ajax로 채워질 때까지 대기."""
    def ready(d):
        try:
            return len(get_site_options(d)) > 0
        except StaleElementReferenceException:
            return False
    WebDriverWait(drv, timeout).until(ready)


def setup_query(drv, year, quarter):
    try:
        drv.get(URL)
    except TimeoutException:
        # 페이지 로딩이 끝나지 않아도 조회 화면이 이미 떠 있는 경우가 많음 → 로딩 중단 후 계속
        try:
            drv.execute_script("window.stop();")
        except Exception:
            pass
    WebDriverWait(drv, 30).until(lambda d: d.find_element(By.XPATH, XP_YEAR))
    select_by_text(drv, XP_YEAR, str(year))
    select_by_text(drv, XP_QUARTER, f"{quarter}분기")
    select_by_text(drv, XP_REGION, REGION_NAME)
    pause()
    wait_site_list(drv)


def click_search(drv):
    btn = drv.find_element(By.XPATH, XP_SEARCH)
    try:
        btn.click()
    except Exception:
        drv.execute_script("arguments[0].click();", btn)  # 가려진 경우 대비


def read_rows(drv):
    """결과표 tbody 의 모든 행을 [[셀, ...], ...] 로. 표가 없으면 None."""
    try:
        return drv.execute_script(JS_READ_ROWS, XP_TBODY)
    except UnexpectedAlertPresentException:
        drv.switch_to.alert.accept()
        return None


def is_empty_rows(rows):
    """'자료가 없습니다' 안내 행(셀 1개)이거나 데이터 행이 없는 경우."""
    if not rows:
        return True
    data_rows = [r for r in rows if len(r) >= N_COLS]
    return len(data_rows) == 0


def wait_result(drv, expected_site, timeout=30, min_wait=2.0):
    """조회 결과가 '이번에 선택한 사업장' 것으로 갱신될 때까지 대기.
    - 데이터 행의 사업장명이 선택한 사업장과 일치하면 즉시 반환
    - 데이터가 없는 사업장이면 min_wait 이후 '자료가 없습니다' 상태를 확인하고 반환
    (이전 사업장의 표가 남아 있는 것을 새 결과로 오인하지 않기 위함)
    """
    want = norm_site(expected_site)
    t0 = time.time()
    while time.time() - t0 < timeout:
        rows = read_rows(drv)
        elapsed = time.time() - t0
        if rows:
            data_rows = [r for r in rows if len(r) >= N_COLS]
            if data_rows:
                got = norm_site(data_rows[0][3])
                if got == want or want in got or got in want:
                    return rows
            elif elapsed >= min_wait:
                return rows  # 자료 없음 상태
        time.sleep(0.5)
    return read_rows(drv)  # 시간 초과: 현재 상태 반환(호출부에서 검증)


def dump_debug(drv, tag):
    DEBUG.mkdir(parents=True, exist_ok=True)
    try:
        html = drv.find_element(By.XPATH, XP_TABLE).get_attribute("outerHTML")
    except NoSuchElementException:
        html = drv.page_source
    (DEBUG / f"{tag}_table.html").write_text(html, encoding="utf-8")


def rows_to_df(rows):
    data = [r[:N_COLS] for r in rows if len(r) >= N_COLS]
    return pd.DataFrame(data, columns=COLS)


def crawl_quarter(drv, year, quarter, limit=None, early_exit=10):
    """early_exit: 폐쇄 표시가 없는 사업장이 앞에서부터 N곳 연속 '자료 없음'이고
    자료가 있는 곳이 한 곳도 없으면, 그 분기의 나머지는 조회하지 않음 (0이면 끔)."""
    tag = f"{year}Q{quarter}"
    outdir = RAW / tag
    outdir.mkdir(parents=True, exist_ok=True)

    setup_query(drv, year, quarter)
    sites = get_site_options(drv)
    pd.DataFrame(sites, columns=["value", "site_name"]).assign(
        closed=lambda d: d.site_name.str.contains("폐쇄")
    ).to_csv(OUT / f"site_list_{tag}.csv", index=False, encoding="utf-8-sig")
    print(f"[{tag}] 사업장 {len(sites)}곳")

    first_dumped = False
    probe_empty = probe_hit = 0  # 조기 종료 판단용 (폐쇄 사업장의 빈 결과는 세지 않음)
    for n, (val, name) in enumerate(sites, 1):
        if limit and n > limit:
            break

        if early_exit and probe_hit == 0 and probe_empty >= early_exit:
            rest = len(sites) - n + 1
            log_skipped_quarter(
                f"{tag} | 앞쪽 {early_exit}곳 모두 자료 없음 → 나머지 {rest}곳 조회 생략")
            break

        fpath = outdir / f"{safe_name(name)}.csv"
        if fpath.exists():
            probe_hit += 1  # 이미 받은 자료가 있는 분기
            continue  # 이어받기
        print(f"[{tag}] ({n}/{len(sites)}) {name}")

        for attempt in range(3):
            try:
                if attempt > 0:  # 재시도 시 화면 초기화
                    setup_query(drv, year, quarter)
                Select(drv.find_element(By.XPATH, XP_SITE)).select_by_value(val)
                pause(0.3, 0.8)
                click_search(drv)
                rows = wait_result(drv, name)
                pause(0.3, 0.8)
                if not first_dumped:
                    dump_debug(drv, tag)
                    first_dumped = True

                if is_empty_rows(rows):
                    log_fail(f"{tag} | {name} | 빈 결과(자료 없음)")
                    if "폐쇄" not in name:
                        probe_empty += 1
                    break

                df = rows_to_df(rows)
                # 선택한 사업장의 결과인지 최종 검증
                got = {norm_site(s) for s in df["사업장명"].unique()}
                want = norm_site(name)
                if not any(want in g or g in want for g in got):
                    raise TimeoutException(f"결과 사업장 불일치: {got}")
                df.to_csv(fpath, index=False, encoding="utf-8-sig")
                probe_hit += 1
                print(f"      → {len(df)}행 저장")
                break
            except (StaleElementReferenceException, TimeoutException,
                    NoSuchElementException, UnexpectedAlertPresentException) as e:
                try:
                    drv.switch_to.alert.accept()
                except Exception:
                    pass
                if attempt == 2:
                    log_fail(f"{tag} | {name} | 오류 {type(e).__name__}: {e}")
                else:
                    pause(2, 4)
        pause()  # 서버 부담을 줄이기 위한 대기


def merge_all():
    """사업장별 CSV 병합 → tms_all_raw.csv, 정제본 → tms_all_clean.csv"""
    files = sorted(RAW.glob("*/*.csv"))
    if not files:
        print("합칠 파일이 없습니다.")
        return
    df = pd.concat((pd.read_csv(f, dtype=str) for f in files), ignore_index=True)
    df.to_csv(OUT / "tms_all_raw.csv", index=False, encoding="utf-8-sig")
    print(f"병합 완료: {len(files)}개 파일, {len(df):,}행 → {OUT / 'tms_all_raw.csv'}")

    # 정제: 잠정치(p) 표시 분리, 숫자 변환, 날짜 생성
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
    bad = clean["날짜"].isna().sum()
    if bad:
        print(f"  [!] 날짜 변환 실패 {bad}행 (일자 형식 확인 필요)")
    clean.to_csv(OUT / "tms_all_clean.csv", index=False, encoding="utf-8-sig")
    print(f"정제본 저장 → {OUT / 'tms_all_clean.csv'} (잠정치 포함 행 {int(prov.sum()):,})")


if __name__ == "__main__":
    fix_console_encoding()

    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="+", type=int, default=[2024, 2025, 2026])
    ap.add_argument("--quarters", nargs="+", type=int, default=[1, 2, 3, 4])
    ap.add_argument("--limit", type=int, default=None, help="분기당 최대 사업장 수(테스트용)")
    ap.add_argument("--show", action="store_true", help="브라우저 창 표시")
    ap.add_argument("--merge", action="store_true", help="수집 없이 병합·정제만")
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
    a = ap.parse_args()

    if a.data_dir:
        OUT = Path(a.data_dir).expanduser().resolve()
        RAW = OUT / "raw"
        DEBUG = OUT / "debug"
    print(f"[데이터 폴더] {OUT}")

    if a.merge:
        merge_all()
    else:
        skip_set = {s.upper() for s in a.skip_quarters}
        drv = make_driver(a.show)
        try:
            for y in a.years:
                for q in a.quarters:
                    tag = f"{y}Q{q}"
                    if tag in skip_set:
                        print(f"[건너뜀] {tag}: 제외 지정")
                        continue
                    if not a.include_open and is_open_quarter(y, q, a.lag_days):
                        print(f"[건너뜀] {tag}: 아직 끝나지 않은 분기 "
                              f"(종료 {quarter_end(y, q)}, --include-open 으로 해제)")
                        continue
                    # 분기 단위 오류가 나도 전체가 중단되지 않게: 최대 3회 시도(이어받기라 안전),
                    # 마지막 시도 전에는 브라우저를 새로 띄움
                    for attempt in range(1, 4):
                        try:
                            crawl_quarter(drv, y, q, a.limit, a.early_exit)
                            break
                        except (TimeoutException, NoSuchElementException,
                                StaleElementReferenceException, WebDriverException) as e:
                            msg = " ".join(str(e).split())[:200]
                            print(f"[{tag}] 분기 오류 ({attempt}/3): {type(e).__name__}: {msg}")
                            if attempt == 3:
                                with open(OUT / "quarter_errors.log", "a", encoding="utf-8") as f:
                                    f.write(f"{tag} | {type(e).__name__}: {msg}\n")
                                break
                            if attempt == 2:
                                try:
                                    drv.quit()
                                except Exception:
                                    pass
                                drv = make_driver(a.show)
                            pause(3 * attempt, 5 * attempt)
        finally:
            try:
                drv.quit()
            except Exception:
                pass
        merge_all()
