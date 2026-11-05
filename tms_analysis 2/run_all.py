# -*- coding: utf-8 -*-
"""
모든 분석을 순서대로 실행(하나가 실패해도 다음으로 진행)
사용: python run_all.py            → 01~23 전부 + 결과 취합(20) + 대시보드
      python run_all.py 05 08 09   → 지정한 번호만(+ 결과 취합 + 대시보드)
실행 기록은 results/_run_log.txt 에 남습니다(오류가 나면 이 파일도 Claude에게 주세요).
"""
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
scripts = sorted(p for p in BASE.glob("[0-9][0-9]_*.py") if not p.name.startswith("20_"))
if len(sys.argv) > 1:
    want = set(sys.argv[1:])
    scripts = [p for p in scripts if p.name[:2] in want]
scripts += [BASE / "20_build_digest.py", BASE / "build_dashboard.py"]   # 항상 마지막에 취합·대시보드

log_dir = BASE / "results"
log_dir.mkdir(exist_ok=True)
with open(log_dir / "_run_log.txt", "a", encoding="utf-8") as log:
    for p in scripts:
        t0 = time.time()
        print(f"\n▶ {p.name}")
        r = subprocess.run([sys.executable, str(p)], cwd=BASE, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        dt = time.time() - t0
        status = "OK" if r.returncode == 0 else f"ERROR({r.returncode})"
        print(r.stdout[-1500:])
        if r.returncode != 0:
            print(r.stderr[-3000:])
        log.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} {p.name} {status} {dt:.0f}s =====\n")
        log.write(r.stdout[-3000:])
        if r.returncode != 0:
            log.write("\n[stderr]\n" + r.stderr[-6000:])
        log.flush()
print("\n끝. results/_run_log.txt, results/00_DIGEST_for_Claude.md, dashboard.html 확인")
