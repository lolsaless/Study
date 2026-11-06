"""
failed.log 에 기록된 (분기, 사업장)만 다시 수집하는 재수집 코드  (멀티 기기 대응판)

[이번 개선 사항]
1) 저장 위치 고정: 어디서 실행하든(VSCode 실행 버튼, 터미널 등) 이 스크립트가 있는 폴더의
   data/ 에 결과가 쌓입니다. (기존에는 '실행한 위치(cwd)' 기준이라 프로젝트 최상위 폴더에
   data/ 가 새로 생겼음)
2) 기기 간 호환: 인텔 맥 / 윈도우 / 맥미니에서 같은 코드로 동작
   - 경로는 pathlib 으로만 처리, 로그 인코딩 자동 판별(utf-8 / utf-8-sig / cp949)
   - 윈도우 콘솔 한글 깨짐·인코딩 오류 방지
   - 필요하면 --data-dir 로 데이터 폴더를 OneDrive/iCloud/외장 등 공유 위치로 지정 가능
3) 실행 이력 누적: data/retry_history.csv 에 (실행시각, 기기명, 결과)를 계속 추가
   → 어느 기기에서 무엇을 복구했는지 확인 가능

- 기본 크롤러(soosiro_tms_2.py / soosiro_tms_1.py / soosiro_tms.py)와 같은 폴더에 두세요.
  (실행 위치는 상관없습니다.)
- 로딩이 늦어서 빈 결과로 오판된 경우를 구하기 위해 대기 시간을 늘려 최대 2회 조회합니다.
  2회 모두 비면 '진짜 자료 없음'으로 확정해 data/confirmed_empty.csv 에 기록합니다.

실행 예:
    # 테스트 (처음 3건만, 브라우저 창 보이게)
    python crawl_failed.py --limit 3 --show

    # 전체 재수집
    python crawl_failed.py

    # 로그 파일/기본 모듈 지정 (상대경로는 현재 위치 → 데이터 폴더 순으로 찾음)
    python crawl_failed.py --log failed_remaining.log --module soosiro_tms_1

    # 데이터 폴더를 다른 곳으로 지정 (예: 동기화 폴더)
    python crawl_failed.py --data-dir "D:/OneDrive/tms_data"

결과 (모두 데이터 폴더 아래):
    raw/{연도}Q{분기}/{사업장명}.csv   복구된 사업장 CSV (기존 폴더에 그대로 추가)
    confirmed_empty.csv               재조회해도 자료가 없는 (분기, 사업장) 확정 목록
    retry_result.csv                  이번 재수집 결과(recovered / confirmed_empty / error)
    retry_history.csv                 실행 때마다 누적되는 이력 (실행시각·기기명 포함)
    failed_remaining.log              여전히 오류로 남은 건 (다음에 --log 로 넘겨 재실행 가능)
    복구된 건이 있으면 마지막에 전체 병합(tms_all_raw / tms_all_clean)을 다시 만듭니다.
"""
import argparse
import importlib
import os
import platform
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    UnexpectedAlertPresentException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

# 이 스크립트가 있는 폴더 = 프로젝트(작업공간) 기준 폴더. 실행 위치(cwd)와 무관하게 고정.
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = SCRIPT_DIR / "data"

LINE = re.compile(r"^\s*(\d{4})Q([1-4])\s*\|\s*(.+?)\s*\|\s*(.*?)\s*$")
# 시도 순서: (조회 후 최소 대기초). 2번째 시도는 화면을 새로 열어서 조회
WAITS = [6.0, 12.0]


# ── 기기/경로 관련 보조 함수 ─────────────────────────────────────────
def fix_console_encoding():
    """윈도우 콘솔(cp949 등)에서 한글/특수문자 출력 오류가 나지 않도록 UTF-8로 맞춤."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def read_text_auto(path: Path) -> str:
    """OS/편집기마다 다른 인코딩(utf-8, BOM 포함 utf-8, cp949)을 자동 판별해서 읽음."""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def resolve_input_path(p: str, orig_cwd: Path, data_dir: Path) -> Path:
    """--log 같은 입력 경로 해석: 절대경로 → 원래 실행 위치 → 데이터 폴더 → 스크립트 폴더 순."""
    path = Path(p).expanduser()
    if path.is_absolute():
        return path
    for root in (orig_cwd, data_dir, SCRIPT_DIR):
        cand = root / path
        if cand.exists():
            return cand.resolve()
    return (data_dir / path.name).resolve()  # 없으면 데이터 폴더 기준 경로로 안내


def remap_value(val, new_data_dir: Path):
    """기본 크롤러의 'data/...' 경로(상대/절대 모두)를 new_data_dir 아래로 옮긴 값을 반환. 해당 없으면 None."""
    if isinstance(val, Path):
        p = val
    elif isinstance(val, str) and (val == "data" or val.startswith(("data/", "data\\"))):
        p = Path(val)
    else:
        return None

    if not p.is_absolute():
        if p.parts and p.parts[0] == "data":
            new = new_data_dir.joinpath(*p.parts[1:])
            return new if isinstance(val, Path) else str(new)
        return None
    try:  # 절대경로가 기본 data 폴더 안을 가리키는 경우
        rel = p.relative_to(DEFAULT_DATA_DIR)
    except ValueError:
        return None
    new = new_data_dir / rel
    return new if isinstance(val, Path) else str(new)


def pin_data_dir(base, data_dir: Path):
    """기본 크롤러 모듈의 경로 상수(OUT, RAW, 로그 파일 등)를 data_dir 기준 절대경로로 고정."""
    for name, val in list(vars(base).items()):
        if name.startswith("__"):
            continue
        new = remap_value(val, data_dir)
        if new is not None:
            setattr(base, name, new)
    # 최소한 OUT 은 반드시 data_dir 이어야 함 (모듈에 OUT 이 있다면)
    if hasattr(base, "OUT"):
        base.OUT = data_dir
    if hasattr(base, "RAW"):
        base.RAW = data_dir / "raw"
    data_dir.mkdir(parents=True, exist_ok=True)


def load_base(name=None):
    """기본 크롤러 모듈을 불러옴 (같은 폴더의 soosiro_tms_3 → _2 → _1 → soosiro_tms 순)."""
    sys.path.insert(0, str(SCRIPT_DIR))
    for n in ([name] if name else ["soosiro_tms_3", "soosiro_tms_2", "soosiro_tms_1", "soosiro_tms"]):
        try:
            return importlib.import_module(n)
        except ModuleNotFoundError as e:
            if e.name != n:
                raise
    raise SystemExit("기본 크롤러 모듈(soosiro_tms_3.py / soosiro_tms_2.py / soosiro_tms_1.py / soosiro_tms.py)을 "
                     "찾지 못했습니다. --module 로 이름을 지정하세요.")


# ── 분기 건너뛰기 ───────────────────────────────────────────────────
def quarter_end(year: int, q: int) -> date:
    """해당 분기의 마지막 날."""
    first_next = date(year + (q == 4), 1 if q == 4 else q * 3 + 1, 1)
    return first_next - timedelta(days=1)


def is_open_quarter(year: int, q: int, lag_days: int = 0) -> bool:
    """아직 끝나지 않은(= 자료가 있을 수 없는) 분기인지. lag_days: 종료 후 자료 반영 지연일."""
    return date.today() <= quarter_end(year, q) + timedelta(days=lag_days)


# ── 로그 파싱 ───────────────────────────────────────────────────────
def parse_log(path: Path):
    """failed.log → [(year, quarter, site_text, reason)] (중복 제거, 순서 유지)."""
    seen, items = set(), []
    for line in read_text_auto(path).splitlines():
        m = LINE.match(line)
        if not m:
            continue
        year, q, name, reason = int(m[1]), int(m[2]), m[3], m[4]
        key = (year, q, name)
        if key in seen:
            continue
        seen.add(key)
        items.append((year, q, name, reason))
    return items


def load_confirmed(base):
    p = base.OUT / "confirmed_empty.csv"
    if p.exists():
        return pd.read_csv(p, dtype=str)
    return pd.DataFrame(columns=["quarter", "site_name"])


SETUP_TRIES = 3  # 분기 화면 설정 최대 시도 횟수 (마지막 시도 전에 브라우저를 새로 띄움)


def short_err(e, n=160):
    """예외를 한 줄 요약 (셀레니움 메시지는 여러 줄이라 로그가 깨지지 않게)."""
    msg = " ".join(l.strip() for l in str(e).splitlines() if l.strip())
    return f"{type(e).__name__}: {msg[:n]}"


def setup_quarter(base, drv, year, q, show):
    """분기 화면 설정 + 사업장 목록 읽기. 실패 시 재시도, 그래도 안 되면 브라우저 재시작.
    반환: (driver, 사업장 옵션 목록). 드라이버가 교체될 수 있으니 반환값을 꼭 다시 받아 쓸 것."""
    last = None
    for attempt in range(1, SETUP_TRIES + 1):
        try:
            base.setup_query(drv, year, q)
            opts = base.get_site_options(drv)
            if not opts:
                raise NoSuchElementException("사업장 목록이 비어 있음")
            return drv, opts
        except Exception as e:
            last = e
            print(f"   [분기 설정 재시도 {attempt}/{SETUP_TRIES}] {short_err(e)}")
            try:
                drv.switch_to.alert.accept()
            except Exception:
                pass
            if attempt == SETUP_TRIES - 1:  # 마지막 시도 전: 브라우저가 꼬였을 가능성 → 새로 시작
                try:
                    drv.quit()
                except Exception:
                    pass
                drv = base.make_driver(show)
            if attempt < SETUP_TRIES:
                base.pause(3 * attempt, 5 * attempt)
    raise last


def fetch_one(base, drv, name, val, min_wait):
    """사업장 1곳 조회 → DataFrame 또는 None(자료 없음). 사업장 불일치 시 예외."""
    Select(drv.find_element(By.XPATH, base.XP_SITE)).select_by_value(val)
    base.pause(0.5, 1.0)
    base.click_search(drv)
    rows = base.wait_result(drv, name, timeout=45, min_wait=min_wait)
    base.pause(0.3, 0.8)
    if base.is_empty_rows(rows):
        return None
    df = base.rows_to_df(rows)
    got = {base.norm_site(s) for s in df["사업장명"].unique()}
    want = base.norm_site(name)
    if not any(want in g or g in want for g in got):
        raise TimeoutException(f"결과 사업장 불일치: {got}")
    return df


def main():
    fix_console_encoding()

    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=None,
                    help="재수집할 로그 파일 (기본: <데이터 폴더>/failed.log)")
    ap.add_argument("--module", default=None, help="기본 크롤러 모듈명 (예: soosiro_tms_1)")
    ap.add_argument("--data-dir", default=None,
                    help="데이터 폴더 (기본: 이 스크립트 옆의 data/). 동기화 폴더 등 지정 가능")
    ap.add_argument("--limit", type=int, default=None, help="테스트용: 처음 N건만")
    ap.add_argument("--show", action="store_true", help="브라우저 창 표시")
    ap.add_argument("--force", action="store_true",
                    help="이미 '확정 빈 결과'로 기록된 건도 다시 조회")
    ap.add_argument("--skip-quarters", nargs="*", default=[], metavar="YYYYQn",
                    help="조회하지 않을 분기 (예: --skip-quarters 2026Q4 2025Q1)")
    ap.add_argument("--include-open", action="store_true",
                    help="아직 끝나지 않은 분기도 조회 (기본: 자동으로 건너뜀)")
    ap.add_argument("--lag-days", type=int, default=0,
                    help="분기 종료 후 자료 반영까지 기다릴 일수 (기본 0)")
    ap.add_argument("--early-exit", type=int, default=5, metavar="N",
                    help="분기 앞쪽 N곳이 모두 '자료 없음'이면 그 분기의 나머지는 조회 생략 "
                         "(기본 5, 0이면 끔)")
    a = ap.parse_args()

    orig_cwd = Path.cwd()
    data_dir = (Path(a.data_dir).expanduser() if a.data_dir else DEFAULT_DATA_DIR)
    if not data_dir.is_absolute():
        data_dir = (orig_cwd / data_dir)
    data_dir = data_dir.resolve()

    # 핵심: 기본 크롤러가 상대경로("data/...")를 쓰더라도 스크립트 폴더 기준이 되도록 고정
    os.chdir(SCRIPT_DIR)
    base = load_base(a.module)
    pin_data_dir(base, data_dir)
    print(f"[환경] {platform.system()} / {platform.node()}")
    print(f"[데이터 폴더] {data_dir}")

    log_path = (resolve_input_path(a.log, orig_cwd, data_dir) if a.log
                else data_dir / "failed.log")
    if not log_path.exists():
        raise SystemExit(f"로그 파일이 없습니다: {log_path}")

    items = parse_log(log_path)
    confirmed = load_confirmed(base)
    done_empty = set(zip(confirmed["quarter"], confirmed["site_name"]))

    skip_set = {s.upper() for s in a.skip_quarters}
    skipped_q = {}  # 분기 → 건너뛴 건수
    targets = []
    for year, q, name, reason in items:
        tag = f"{year}Q{q}"
        if (base.RAW / tag / f"{base.safe_name(name)}.csv").exists():
            continue  # 이미 복구됨 (다른 기기에서 복구한 것 포함)
        if (tag, name) in done_empty and not a.force:
            continue  # 이전에 확정된 빈 결과
        if tag in skip_set or (not a.include_open and is_open_quarter(year, q, a.lag_days)):
            skipped_q[tag] = skipped_q.get(tag, 0) + 1
            continue  # 지정 제외 분기 / 아직 끝나지 않은 분기
        targets.append((year, q, name, reason))
    for tag, n_skip in sorted(skipped_q.items()):
        print(f"[건너뜀] {tag}: {n_skip}건 (제외 지정 또는 아직 끝나지 않은 분기)")
    if a.limit:
        targets = targets[: a.limit]
    print(f"로그 {len(items)}건 중 재수집 대상 {len(targets)}건")
    if not targets:
        return

    # 분기별로 묶어서 처리 (분기당 화면 설정 1회)
    by_q = {}
    for year, q, name, reason in targets:
        by_q.setdefault((year, q), []).append((name, reason))

    results = []  # (quarter, site, status, detail)
    drv = base.make_driver(a.show)
    try:
        for (year, q), lst in by_q.items():
            tag = f"{year}Q{q}"
            (base.RAW / tag).mkdir(parents=True, exist_ok=True)
            try:
                drv, opts = setup_quarter(base, drv, year, q, a.show)
            except Exception as e:  # 재시도·브라우저 재시작 후에도 분기 화면 설정 실패
                msg = short_err(e)
                print(f"[{tag}] 분기 설정 최종 실패 → 이 분기 {len(lst)}건은 오류로 남김: {msg}")
                for name, _ in lst:
                    results.append((tag, name, "error", f"분기 설정 실패 {msg}"))
                continue
            val_by_text = {t: v for v, t in opts}
            val_by_norm = {base.norm_site(t): v for v, t in opts}

            n_empty = n_recovered = 0  # 분기 단위 조기 종료 판단용
            for idx, (name, reason) in enumerate(lst):
                if (a.early_exit and idx >= a.early_exit
                        and n_recovered == 0 and n_empty >= a.early_exit):
                    # 앞쪽 N곳이 전부 빈 결과 → 이 분기는 자료 미공개로 보고 나머지 생략
                    rest = lst[idx:]
                    print(f"[{tag}] 앞 {a.early_exit}곳 모두 자료 없음 → 나머지 {len(rest)}건 조회 생략")
                    for rname, _ in rest:
                        results.append((tag, rname, "skipped", "분기 조기 종료(앞쪽 모두 자료 없음)"))
                    break
                val = val_by_text.get(name) or val_by_norm.get(base.norm_site(name))
                print(f"[{tag}] {name}")
                if not val:
                    results.append((tag, name, "error", "사업장 목록에 없음"))
                    print("   → 오류 사업장 목록에 없음")
                    continue

                status, detail, df = "confirmed_empty", "2회 조회 모두 자료 없음", None
                for attempt, min_wait in enumerate(WAITS):
                    try:
                        if attempt > 0:  # 2번째 시도: 화면을 새로 열고 더 길게 대기
                            base.setup_query(drv, year, q)
                        df = fetch_one(base, drv, name, val, min_wait)
                        if df is not None:
                            status, detail = "recovered", f"{len(df)}행"
                            break
                    except (StaleElementReferenceException, TimeoutException,
                            NoSuchElementException, UnexpectedAlertPresentException,
                            WebDriverException) as e:
                        try:
                            drv.switch_to.alert.accept()
                        except Exception:
                            pass
                        status, detail = "error", short_err(e)
                        base.pause(2, 4)

                if status == "recovered":
                    df.to_csv(base.RAW / tag / f"{base.safe_name(name)}.csv",
                              index=False, encoding="utf-8-sig")
                    print(f"   → 복구 {detail}")
                elif status == "confirmed_empty":
                    print("   → 진짜 자료 없음 확정")
                else:
                    print(f"   → 오류 {detail}")
                if status == "recovered":
                    n_recovered += 1
                elif status == "confirmed_empty":
                    n_empty += 1
                results.append((tag, name, status, detail))
                base.pause()
    finally:
        try:
            drv.quit()
        except Exception:
            pass

    # ── 결과 정리 ───────────────────────────────────────────────────
    res = pd.DataFrame(results, columns=["quarter", "site_name", "status", "detail"])
    res.to_csv(base.OUT / "retry_result.csv", index=False, encoding="utf-8-sig")

    # 실행 이력 누적 (기기 간 번갈아 작업해도 기록이 남음)
    hist = res.copy()
    hist.insert(0, "host", platform.node())
    hist.insert(0, "run_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    hist_path = base.OUT / "retry_history.csv"
    hist.to_csv(hist_path, mode="a", header=not hist_path.exists(),
                index=False, encoding="utf-8-sig")

    new_empty = res[res.status == "confirmed_empty"][["quarter", "site_name"]]
    if len(new_empty):
        pd.concat([confirmed, new_empty], ignore_index=True) \
            .drop_duplicates().to_csv(base.OUT / "confirmed_empty.csv",
                                      index=False, encoding="utf-8-sig")

    err = res[res.status == "error"]
    rem = base.OUT / "failed_remaining.log"
    if len(err):
        rem.write_text("\n".join(f"{r.quarter} | {r.site_name} | 오류 {r.detail}"
                                 for r in err.itertuples()) + "\n", encoding="utf-8")
    elif rem.exists():
        rem.unlink()

    n = res.status.value_counts()
    print("\n=== 재수집 결과 ===")
    print(f"복구 {n.get('recovered', 0)}건 / 자료 없음 확정 {n.get('confirmed_empty', 0)}건 / "
          f"오류 {n.get('error', 0)}건 / 조기 종료로 생략 {n.get('skipped', 0)}건")
    if len(err):
        print(f"오류 건은 {rem} 에 있습니다. "
              f"다시 시도: python crawl_failed.py --log failed_remaining.log")

    if n.get("recovered", 0) and hasattr(base, "merge_all"):
        base.merge_all()


if __name__ == "__main__":
    main()
