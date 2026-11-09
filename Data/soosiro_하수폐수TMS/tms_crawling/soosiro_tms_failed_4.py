"""
failed.log 에 기록된 (분기, 사업장)만 다시 수집하는 재수집 코드  -  v4 (장애 자동복구판)

[v4 변경 사항]
1) soosiro_tms_4.py 의 자동복구 브라우저(Session)를 그대로 사용
   (타임아웃·크롬 종료·알림창이 나도 재시도 → 재시작 → 모드 상승으로 스스로 복구)
2) 결과를 건마다 즉시 저장 (복구 CSV·확정 빈 결과·실행 이력)
   → 중간에 끊겨도(Ctrl+C, 정전, 연속 오류로 자동 종료) 이미 확인한 건은 다시 조회하지 않음
3) failed.log 의 줄붙음(앞 줄 끝에 다음 기록이 붙은 경우)·중복·인코딩 혼재를 자동 보정
4) 끝나면 해결된 건을 failed.log 에서 제거(원본은 failed.log.bak 으로 보관) → 로그가 누적되지 않음
5) 이전 버전의 '분기 조기 종료'는 제거: 재수집 대상은 이미 '의심 목록'이라 앞쪽이 전부 비는 게 정상이고,
   그걸로 나머지를 건너뛰면 복구 가능한 건을 놓칠 수 있기 때문 (조기 종료는 크롤러 본체에만 있음)
6) 빈 결과 확정: 조회 전 표를 표시해 '새로 그려진 뒤'에도 비어 있는 경우만 확정,
   2회(화면을 새로 열어서) 모두 비면 '진짜 자료 없음'

- soosiro_tms_4.py 와 같은 폴더에 두세요. (실행 위치는 상관없습니다.)

실행 예:
    # 테스트 (처음 3건만, 브라우저 창 보이게)
    python soosiro_tms_failed_4.py --limit 3 --show

    # 전체 재수집
    python soosiro_tms_failed_4.py

    # 오류로 남은 건만 다시
    python soosiro_tms_failed_4.py --log failed_remaining.log

    # 데이터 폴더를 다른 곳으로 지정 (예: 동기화 폴더)
    python soosiro_tms_failed_4.py --data-dir "D:/OneDrive/tms_data"

결과 (모두 데이터 폴더 아래):
    raw/{연도}Q{분기}/{사업장명}.csv   복구된 사업장 CSV (기존 폴더에 그대로 추가)
    confirmed_empty.csv               재조회해도 자료가 없는 (분기, 사업장) 확정 목록 (건마다 즉시 기록)
    retry_result.csv                  이번 재수집 결과(recovered / confirmed_empty / error)
    retry_history.csv                 실행 때마다 누적되는 이력 (실행시각·기기명 포함)
    failed_remaining.log              여전히 오류로 남은 건 (다음에 --log 로 넘겨 재실행 가능)
    run.log                           실행 기록(시각·오류 원인·진단)
    복구된 건이 있으면 마지막에 전체 병합(tms_all_raw / tms_all_clean)을 다시 만듭니다.
"""
import argparse
import csv
import importlib
import os
import platform
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = SCRIPT_DIR / "data"
DEFAULT_WAITS = (5.0, 10.0)  # 시도별 '빈 결과 유지 확인' 초. 2번째는 화면을 새로 열어 재조회


def load_base(name=None):
    """기본 크롤러 모듈(soosiro_tms_4)을 불러옴."""
    sys.path.insert(0, str(SCRIPT_DIR))
    n = name or "soosiro_tms_4"
    try:
        mod = importlib.import_module(n)
    except ModuleNotFoundError as e:
        if e.name != n:
            raise
        raise SystemExit(f"기본 크롤러 모듈 {n}.py 를 찾지 못했습니다. "
                         f"이 파일과 같은 폴더({SCRIPT_DIR})에 두세요.")
    if not hasattr(mod, "Session"):
        raise SystemExit(f"{n}.py 는 자동복구판(v4)이 아닙니다. soosiro_tms_4.py 를 사용하세요.")
    return mod


def resolve_input_path(p, orig_cwd, data_dir):
    """--log 경로 해석: 절대경로 → 원래 실행 위치 → 데이터 폴더 → 스크립트 폴더 순."""
    path = Path(p).expanduser()
    if path.is_absolute():
        return path
    for root in (orig_cwd, data_dir, SCRIPT_DIR):
        cand = root / path
        if cand.exists():
            return cand.resolve()
    return (data_dir / path.name).resolve()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=None, help="재수집할 로그 파일 (기본: <데이터 폴더>/failed.log)")
    ap.add_argument("--module", default=None, help="기본 크롤러 모듈명 (기본: soosiro_tms_4)")
    ap.add_argument("--data-dir", default=None,
                    help="데이터 폴더 (기본: 이 스크립트 옆의 data/). 동기화 폴더 등 지정 가능")
    ap.add_argument("--limit", type=int, default=None, help="테스트용: 처음 N건만")
    ap.add_argument("--show", action="store_true", help="브라우저 창 표시")
    ap.add_argument("--force", action="store_true", help="이미 '확정 빈 결과'로 기록된 건도 다시 조회")
    ap.add_argument("--skip-quarters", nargs="*", default=[], metavar="YYYYQn",
                    help="조회하지 않을 분기 (예: --skip-quarters 2026Q4 2025Q1)")
    ap.add_argument("--include-open", action="store_true",
                    help="아직 끝나지 않은 분기도 조회 (기본: 자동으로 건너뜀)")
    ap.add_argument("--lag-days", type=int, default=0, help="분기 종료 후 자료 반영까지 기다릴 일수 (기본 0)")
    ap.add_argument("--waits", nargs="+", type=float, default=list(DEFAULT_WAITS), metavar="SEC",
                    help="빈 결과 확인 시도별 대기초 (기본 5 10 → 2회 모두 비어야 '자료 없음' 확정)")
    ap.add_argument("--no-compact", action="store_true", help="끝난 뒤 failed.log 정리를 하지 않음")
    ap.add_argument("--with-images", action="store_true", help="이미지 로딩 허용 (기본: 차단해 속도 향상)")
    ap.add_argument("--level", type=int, default=0, choices=range(3),
                    help="브라우저 모드 시작 단계 (0=헤드리스 eager, 1=헤드리스 none, 2=일반 창)")
    a = ap.parse_args()

    orig_cwd = Path.cwd()
    data_dir = Path(a.data_dir).expanduser() if a.data_dir else DEFAULT_DATA_DIR
    if not data_dir.is_absolute():
        data_dir = orig_cwd / data_dir
    data_dir = data_dir.resolve()

    os.chdir(SCRIPT_DIR)
    base = load_base(a.module)
    base.fix_console_encoding()
    base.set_data_dir(data_dir)
    base.rotate_run_log()
    say = base.say
    say(f"[환경] {platform.system()} / {platform.node()}   [데이터 폴더] {data_dir}")

    log_path = resolve_input_path(a.log, orig_cwd, data_dir) if a.log else data_dir / "failed.log"
    if not log_path.exists():
        raise SystemExit(f"로그 파일이 없습니다: {log_path}")

    base.cleanup_partial()
    items = base.read_failed_log(log_path)
    confirmed = base.load_confirmed()

    skip_set = {s.upper() for s in a.skip_quarters}
    skipped_q, targets = {}, []
    for year, q, name, reason in items:
        tag = f"{year}Q{q}"
        if base.have_data(tag, name):
            continue  # 이미 복구됨 (다른 기기에서 복구한 것 포함)
        if (tag, name) in confirmed and not a.force:
            continue  # 이전에 확정된 빈 결과
        if tag in skip_set or (not a.include_open and base.is_open_quarter(year, q, a.lag_days)):
            skipped_q[tag] = skipped_q.get(tag, 0) + 1
            continue  # 지정 제외 분기 / 아직 끝나지 않은 분기
        targets.append((year, q, name))
    for tag, n_skip in sorted(skipped_q.items()):
        say(f"[건너뜀] {tag}: {n_skip}건 (제외 지정 또는 아직 끝나지 않은 분기)")
    if a.limit:
        targets = targets[: a.limit]
    say(f"로그 {len(items)}건 중 재수집 대상 {len(targets)}건")

    by_q = {}
    for year, q, name in targets:
        by_q.setdefault((year, q), []).append(name)

    results = []  # (quarter, site, status, detail)
    hist_path = data_dir / "retry_history.csv"
    host = platform.node()

    def record(tag, name, status, detail):
        """결과를 목록과 이력 파일에 즉시 기록 (중간에 끊겨도 보존)."""
        results.append((tag, name, status, detail))
        try:
            new = (not hist_path.exists()) or hist_path.stat().st_size == 0
            base._ensure_trailing_newline(hist_path)
            with open(hist_path, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
                w = csv.writer(f, lineterminator="\n")
                if new:
                    w.writerow(["run_at", "host", "quarter", "site_name", "status", "detail"])
                w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), host, tag, name, status, detail])
        except Exception as e:
            say(f"  [!] 이력 기록 실패(무시하고 계속): {base.short_err(e, 80)}")

    stopped = ""
    sess = None
    if targets:
        st, info = base.probe_site()
        say("[사이트 점검] " + (f"HTTP {st}, 응답 {info:.1f}초" if st
                               else f"직접 접속 실패({base.short_err(info, 80)}) → 브라우저로 계속 시도합니다"))
        try:
            sess = base.Session(show=a.show, images=a.with_images, level=a.level)
            for (year, q), names in by_q.items():
                tag = f"{year}Q{q}"
                (base.RAW / tag).mkdir(parents=True, exist_ok=True)
                ctx = base.QuarterCtx(sess, year, q)
                try:
                    ctx.open()
                except (base.GiveUp, base.BrowserUnavailable):
                    raise
                except Exception as e:  # 재시도·브라우저 재시작 후에도 분기 화면 설정 실패
                    msg = base.short_err(e)
                    say(f"[{tag}] 분기 화면 설정 최종 실패 → 이 분기 {len(names)}건은 오류로 남김: {msg}")
                    for name in names:
                        record(tag, name, "error", f"분기 설정 실패 {msg}")
                    continue

                for name in names:
                    say(f"[{tag}] {name}")
                    r = ctx.fetch(name, waits=tuple(a.waits))
                    if r.status == "data":
                        base.save_csv_atomic(r.df, base.RAW / tag / f"{base.safe_name(name)}.csv")
                        say(f"   → 복구 {r.detail}")
                        record(tag, name, "recovered", r.detail)
                    elif r.status == "empty":
                        base.add_confirmed(tag, name)
                        say("   → 진짜 자료 없음 확정")
                        record(tag, name, "confirmed_empty", r.detail)
                    else:
                        say(f"   → 오류 {r.detail}")
                        record(tag, name, "error", r.detail)
                    base.pause()
        except base.GiveUp as e:
            stopped = (f"[중단] {e}. 사이트 점검이나 네트워크 문제일 수 있습니다. "
                       f"잠시 뒤 같은 명령을 다시 실행하면 처리한 건은 건너뛰고 이어서 받습니다.")
        except base.BrowserUnavailable as e:
            stopped = f"[중단] {e}"
        except KeyboardInterrupt:
            stopped = "[중단] 사용자가 중단했습니다. 처리한 건은 저장돼 있어 다시 실행하면 이어서 받습니다."
        finally:
            if sess:
                sess.stop()
    if stopped:
        say(stopped)

    # ── 결과 정리 (각 단계가 실패해도 다음 단계 진행) ─────────────────
    def safe(label, fn):
        try:
            return fn()
        except Exception as e:
            say(f"  [!] {label} 중 문제(무시하고 계속): {base.short_err(e, 120)}")

    def write_result():
        with open(data_dir / "retry_result.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["quarter", "site_name", "status", "detail"])
            w.writerows(results)

    def write_remaining():
        rem = data_dir / "failed_remaining.log"
        errs = [r for r in results if r[2] == "error"]
        if errs:
            base.write_text_atomic(rem, "\n".join(f"{t} | {n} | 오류 {d}" for t, n, _, d in errs) + "\n")
        elif rem.exists():
            rem.unlink()
        return len(errs)

    safe("결과 저장", write_result)
    n_err = safe("남은 오류 정리", write_remaining) or 0

    counts = {}
    for _, _, status, _ in results:
        counts[status] = counts.get(status, 0) + 1
    say("\n=== 재수집 결과 ===")
    say(f"복구 {counts.get('recovered', 0)}건 / 자료 없음 확정 {counts.get('confirmed_empty', 0)}건 / "
        f"오류 {counts.get('error', 0)}건 / 처리 대상 {len(targets)}건 중 처리 {len(results)}건")
    if n_err:
        say(f"오류 건은 {data_dir / 'failed_remaining.log'} 에 있습니다. "
            f"다시 시도: python soosiro_tms_failed_4.py --log failed_remaining.log")
    if len(results) < len(targets):
        say(f"처리하지 못한 {len(targets) - len(results)}건은 같은 명령을 다시 실행하면 이어서 처리합니다.")

    if (not a.no_compact) and log_path.resolve() == (data_dir / "failed.log").resolve() and log_path.exists():
        r = safe("failed.log 정리", lambda: base.compact_failed_log(log_path))
        if r:
            say(f"[로그 정리] failed.log {r[0]}건 → 미해결 {r[1]}건만 남김 (원본: failed.log.bak)")

    if counts.get("recovered", 0):
        safe("전체 병합", base.merge_all)


if __name__ == "__main__":
    main()
