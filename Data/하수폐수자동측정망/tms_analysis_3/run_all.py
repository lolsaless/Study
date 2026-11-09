# -*- coding: utf-8 -*-
"""
분석 일괄 실행(하나가 실패해도 다음으로 진행) — 실행 전 작업안내서.md 를 먼저 읽으세요.

  python run_all.py              → 00 점검 + 기본(1x) → 중급(2x) → 심화(3x) → 연계(4x) → 90 취합   (01·02 준비는 제외)
  python run_all.py prep         → 01·02 준비(원자료·보조자료 표준화)만
  python run_all.py basic        → 기본 분석(10~19)       mid → 20~29 · adv → 30~39 · link → 40~49
  python run_all.py full         → 준비부터 전부
  python run_all.py 22 33        → 지정 번호만
마지막에는 항상 90(결과 취합)이 실행된다. 기록: results/_run_log.txt
"""
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
STAGES = {"prep": "0", "basic": "1", "mid": "2", "adv": "3", "link": "4"}
GUIDE = BASE / "작업안내서.md"


def pick(args):
    allp = sorted(p for p in BASE.glob("[0-9][0-9]_*.py"))
    if not args:
        return [p for p in allp if p.name[:2] == "00" or p.name[0] in "1234"]
    if args == ["full"]:
        return [p for p in allp if p.name[0] in "01234"]
    out = []
    for a in args:
        if a in STAGES:
            out += [p for p in allp if p.name[0] == STAGES[a] and (a != "prep" or p.name[:2] != "00")]
        else:
            out += [p for p in allp if p.name[:2] == a.zfill(2)]
    return out


def main():
    if GUIDE.exists():
        print(f"※ 작업 전 확인: {GUIDE.name} (새 자료 추가 절차·규칙)\n")
    scripts = [p for p in pick(sys.argv[1:]) if not p.name.startswith("90_")] + [BASE / "90_build_digest.py"]
    log_dir = BASE / "results"
    log_dir.mkdir(exist_ok=True)
    summary = []
    with open(log_dir / "_run_log.txt", "a", encoding="utf-8") as log:
        for p in scripts:
            t0 = time.time()
            print(f"▶ {p.name}", flush=True)
            r = subprocess.run([sys.executable, str(p)], cwd=BASE, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            dt = time.time() - t0
            status = "OK" if r.returncode == 0 else f"ERROR({r.returncode})"
            tail = [ln for ln in r.stdout.strip().splitlines() if ln.startswith("[완료]")]
            print(f"   {status} {dt:.0f}s  {tail[-1] if tail else ''}")
            if r.returncode != 0:
                print("   " + r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "")
            log.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} {p.name} {status} {dt:.0f}s =====\n")
            log.write(r.stdout[-3000:])
            if r.returncode != 0:
                log.write("\n[stderr]\n" + r.stderr[-6000:])
            log.flush()
            summary.append((p.name, status, dt))
    bad = [s for s in summary if s[1] != "OK"]
    print(f"\n끝: {len(summary) - len(bad)}/{len(summary)} 성공" + (f" · 실패 {[b[0] for b in bad]} (results/_run_log.txt)" if bad else ""))
    print("다음: results/00_핵심결과.md → results/00_DIGEST_for_Claude.md")


if __name__ == "__main__":
    main()
