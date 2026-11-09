"""
SOOSIRO 수질TMS 사업장별 배출량(일) 크롤러 (Selenium)

사용 준비:
    pip install selenium pandas lxml
    (Selenium 4.6+ 는 크롬드라이버를 자동으로 받아옵니다. 크롬 브라우저만 설치돼 있으면 됩니다.)

실행 예:
    # 1) 먼저 구조 확인용 (경기도 2025년 1분기, 사업장 3곳만, 브라우저 창 보이게)
    python crawl_tms.py --years 2025 --quarters 1 --limit 3 --show

    # 2) 전체 수집 (2024~2026, 1~4분기). 중단 후 다시 실행하면 받은 건 건너뜀
    python crawl_tms.py --years 2024 2025 2026 --quarters 1 2 3 4

결과:
    data/raw/{연도}Q{분기}/{사업장명}.csv   사업장별 원본 표
    data/site_list_{연도}Q{분기}.csv       사업장 목록(폐쇄 표시 포함)
    data/failed.log                        실패·빈 결과 기록
    data/debug/                            첫 실행 시 저장하는 페이지 HTML (구조 확인용)
"""
import argparse
import random
import re
import time
from io import StringIO
from pathlib import Path

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    UnexpectedAlertPresentException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait

URL = "https://www.soosiro.or.kr/open/web/daily?pMENU_NO=419"

# ── 사용자가 확인해준 XPath ───────────────────────────────────────────
XP_YEAR = "/html/body/div[1]/div[3]/div[3]/form[2]/div/dl[1]/dd/ul/li/select"
XP_QUARTER = "/html/body/div[1]/div[3]/div[3]/form[2]/div/dl[2]/dd/select"
XP_REGION = "/html/body/div[1]/div[3]/div[3]/form[2]/div/dl[3]/dd/select"
XP_SITE = "/html/body/div[1]/div[3]/div[3]/form[2]/div/dl[4]/dd[1]/select"
XP_SEARCH = "/html/body/div[1]/div[3]/div[3]/form[2]/div/ul/li[2]/a"

REGION_NAME = "경기도"
OUT = Path("data")
RAW = OUT / "raw"
DEBUG = OUT / "debug"


def pause(a=0.6, b=1.4):
    time.sleep(random.uniform(a, b))


def safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", s).strip("_")


def log_fail(msg: str):
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "failed.log", "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print("  [!]", msg)


def make_driver(show: bool):
    opt = Options()
    if not show:
        opt.add_argument("--headless=new")
    opt.add_argument("--window-size=1400,1000")
    opt.add_argument("--lang=ko-KR")
    drv = webdriver.Chrome(options=opt)
    drv.set_page_load_timeout(60)
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
    drv.get(URL)
    WebDriverWait(drv, 20).until(lambda d: d.find_element(By.XPATH, XP_YEAR))
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


def parse_result(drv):
    """현재 페이지에서 결과 표를 찾아 DataFrame으로. 없으면 None.
    - '자료가 없습니다' 문구면 None
    - 여러 표 중 '배출' 관련 헤더가 있거나 가장 행이 많은 표를 선택
    - 표가 iframe 안에 있는 경우도 탐색
    """
    def try_page():
        html = drv.page_source
        if "자료가 없습니다" in html and "<td" not in html.split("자료가 없습니다")[0][-400:]:
            pass  # 아래에서 표 유무로 최종 판단
        try:
            tables = pd.read_html(StringIO(html))
        except ValueError:
            return None
        best, best_score = None, -1
        for t in tables:
            head = " ".join(map(str, t.columns))
            score = len(t) + (1000 if ("배출" in head or "pH" in head or "TOC" in head) else 0)
            if score > best_score:
                best, best_score = t, score
        return best

    df = try_page()
    if df is None:
        for fr in drv.find_elements(By.TAG_NAME, "iframe"):
            drv.switch_to.frame(fr)
            try:
                df = try_page()
            finally:
                drv.switch_to.default_content()
            if df is not None:
                break
    if df is not None and len(df) == 0:
        return None
    return df


def wait_result(drv, timeout=25):
    """결과 표 또는 '자료가 없습니다' 가 나타날 때까지 대기."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            html = drv.page_source
            if "자료가 없습니다" in html:
                # 표 데이터행이 같이 있는지는 parse_result 에서 판단
                return
            if drv.find_elements(By.CSS_SELECTOR, "table tbody tr td"):
                return
        except UnexpectedAlertPresentException:
            drv.switch_to.alert.accept()
        time.sleep(0.5)


def dump_debug(drv, tag):
    DEBUG.mkdir(parents=True, exist_ok=True)
    (DEBUG / f"{tag}.html").write_text(drv.page_source, encoding="utf-8")


def crawl_quarter(drv, year, quarter, limit=None):
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
    for n, (val, name) in enumerate(sites, 1):
        if limit and n > limit:
            break
        fpath = outdir / f"{safe_name(name)}.csv"
        if fpath.exists():
            continue  # 이어받기
        print(f"[{tag}] ({n}/{len(sites)}) {name}")

        for attempt in range(3):
            try:
                if attempt > 0:  # 재시도 시 화면 초기화
                    setup_query(drv, year, quarter)
                Select(drv.find_element(By.XPATH, XP_SITE)).select_by_value(val)
                pause(0.3, 0.8)
                click_search(drv)
                wait_result(drv)
                pause(0.5, 1.0)
                if not first_dumped:
                    dump_debug(drv, f"{tag}_first_result")
                    first_dumped = True
                df = parse_result(drv)
                if df is None:
                    log_fail(f"{tag} | {name} | 빈 결과")
                else:
                    df.insert(0, "site_name", name)
                    df.insert(0, "quarter", tag)
                    df.to_csv(fpath, index=False, encoding="utf-8-sig")
                break
            except (StaleElementReferenceException, TimeoutException,
                    NoSuchElementException, UnexpectedAlertPresentException) as e:
                try:
                    drv.switch_to.alert.accept()
                except Exception:
                    pass
                if attempt == 2:
                    log_fail(f"{tag} | {name} | 오류 {type(e).__name__}")
                else:
                    pause(2, 4)
        pause()  # 서버 부담을 줄이기 위한 대기


def merge_all():
    """수집된 사업장별 CSV를 하나로 합치기 (data/tms_all_raw.csv)."""
    files = sorted(RAW.glob("*/*.csv"))
    if not files:
        print("합칠 파일이 없습니다.")
        return
    df = pd.concat((pd.read_csv(f) for f in files), ignore_index=True)
    df.to_csv(OUT / "tms_all_raw.csv", index=False, encoding="utf-8-sig")
    print(f"병합 완료: {len(files)}개 파일, {len(df):,}행 → data/tms_all_raw.csv")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="+", type=int, default=[2024, 2025, 2026])
    ap.add_argument("--quarters", nargs="+", type=int, default=[1, 2, 3, 4])
    ap.add_argument("--limit", type=int, default=None, help="분기당 최대 사업장 수(테스트용)")
    ap.add_argument("--show", action="store_true", help="브라우저 창 표시")
    ap.add_argument("--merge", action="store_true", help="수집 없이 병합만")
    a = ap.parse_args()

    if a.merge:
        merge_all()
    else:
        drv = make_driver(a.show)
        try:
            for y in a.years:
                for q in a.quarters:
                    crawl_quarter(drv, y, q, a.limit)
        finally:
            drv.quit()
        merge_all()
