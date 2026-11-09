"""
failed.log 에 기록된 (분기, 사업장)만 다시 수집하는 재수집 코드

- 기본 크롤러(soosiro_tms_1.py 또는 soosiro_tms.py)와 같은 폴더에 두고, 같은 위치(작업 폴더)에서 실행하세요.
  (data/ 폴더를 상대경로로 쓰기 때문에, 처음 크롤링한 때와 같은 폴더에서 실행해야 합니다.)
- 로딩이 늦어서 빈 결과로 오판된 경우를 구하기 위해 대기 시간을 늘려 최대 2회 조회합니다.
  2회 모두 비면 '진짜 자료 없음'으로 확정해 data/confirmed_empty.csv 에 기록합니다.

실행 예:
    # 테스트 (처음 3건만, 브라우저 창 보이게)
    python crawl_failed.py --limit 3 --show

    # 전체 재수집
    python crawl_failed.py

    # 로그 파일/기본 모듈 지정
    python crawl_failed.py --log data/failed.log --module soosiro_tms_1

결과:
    data/raw/{연도}Q{분기}/{사업장명}.csv   복구된 사업장 CSV (기존 폴더에 그대로 추가)
    data/confirmed_empty.csv               재조회해도 자료가 없는 (분기, 사업장) 확정 목록
    data/retry_result.csv                  이번 재수집 결과(recovered / confirmed_empty / error)
    data/failed_remaining.log              여전히 오류로 남은 건 (다음에 --log 로 넘겨 재실행 가능)
    복구된 건이 있으면 마지막에 전체 병합(tms_all_raw / tms_all_clean)을 다시 만듭니다.
"""
import argparse
import importlib
import re
import sys
from pathlib import Path

import pandas as pd
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    UnexpectedAlertPresentException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

LINE = re.compile(r"^\s*(\d{4})Q([1-4])\s*\|\s*(.+?)\s*\|\s*(.*?)\s*$")
# 시도 순서: (조회 후 최소 대기초). 2번째 시도는 화면을 새로 열어서 조회
WAITS = [6.0, 12.0]


def load_base(name=None):
    """기본 크롤러 모듈을 불러옴 (같은 폴더의 soosiro_tms_1.py → soosiro_tms.py 순)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path.cwd()))
    for n in ([name] if name else ["soosiro_tms_2", "soosiro_tms_1", "soosiro_tms"]):
        try:
            return importlib.import_module(n)
        except ModuleNotFoundError as e:
            if e.name != n:
                raise
    raise SystemExit("기본 크롤러 모듈(soosiro_tms_1.py / soosiro_tms.py)을 찾지 못했습니다. "
                     "--module 로 이름을 지정하세요.")


def parse_log(path: Path):
    """failed.log → [(year, quarter, site_text, reason)] (중복 제거, 순서 유지)."""
    seen, items = set(), []
    for line in path.read_text(encoding="utf-8").splitlines():
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="data/failed.log")
    ap.add_argument("--module", default=None, help="기본 크롤러 모듈명 (예: soosiro_tms_1)")
    ap.add_argument("--limit", type=int, default=None, help="테스트용: 처음 N건만")
    ap.add_argument("--show", action="store_true", help="브라우저 창 표시")
    ap.add_argument("--force", action="store_true",
                    help="이미 '확정 빈 결과'로 기록된 건도 다시 조회")
    a = ap.parse_args()

    base = load_base(a.module)
    log_path = Path(a.log)
    if not log_path.exists():
        raise SystemExit(f"로그 파일이 없습니다: {log_path}")

    items = parse_log(log_path)
    confirmed = load_confirmed(base)
    done_empty = set(zip(confirmed["quarter"], confirmed["site_name"]))

    targets = []
    for year, q, name, reason in items:
        tag = f"{year}Q{q}"
        if (base.RAW / tag / f"{base.safe_name(name)}.csv").exists():
            continue  # 이미 복구됨
        if (tag, name) in done_empty and not a.force:
            continue  # 이전에 확정된 빈 결과
        targets.append((year, q, name, reason))
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
                base.setup_query(drv, year, q)
                opts = base.get_site_options(drv)
            except Exception as e:  # 분기 화면 설정 실패
                for name, _ in lst:
                    results.append((tag, name, "error", f"분기 설정 실패 {type(e).__name__}"))
                    base.log_fail(f"{tag} | {name} | 분기 설정 실패")
                continue
            val_by_text = {t: v for v, t in opts}
            val_by_norm = {base.norm_site(t): v for v, t in opts}

            for name, reason in lst:
                val = val_by_text.get(name) or val_by_norm.get(base.norm_site(name))
                print(f"[{tag}] {name}")
                if not val:
                    results.append((tag, name, "error", "사업장 목록에 없음"))
                    base.log_fail(f"{tag} | {name} | 사업장 목록에 없음")
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
                            NoSuchElementException, UnexpectedAlertPresentException) as e:
                        try:
                            drv.switch_to.alert.accept()
                        except Exception:
                            pass
                        status, detail = "error", f"{type(e).__name__}: {e}"
                        base.pause(2, 4)

                if status == "recovered":
                    df.to_csv(base.RAW / tag / f"{base.safe_name(name)}.csv",
                              index=False, encoding="utf-8-sig")
                    print(f"   → 복구 {detail}")
                elif status == "confirmed_empty":
                    print("   → 진짜 자료 없음 확정")
                else:
                    print(f"   → 오류 {detail}")
                results.append((tag, name, status, detail))
                base.pause()
    finally:
        drv.quit()

    # ── 결과 정리 ───────────────────────────────────────────────────
    res = pd.DataFrame(results, columns=["quarter", "site_name", "status", "detail"])
    res.to_csv(base.OUT / "retry_result.csv", index=False, encoding="utf-8-sig")

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
          f"오류 {n.get('error', 0)}건")
    if len(err):
        print("오류 건은 data/failed_remaining.log 에 있습니다. "
              "다시 시도: python crawl_failed.py --log data/failed_remaining.log")

    if n.get("recovered", 0) and hasattr(base, "merge_all"):
        base.merge_all()


if __name__ == "__main__":
    main()
