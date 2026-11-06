# -*- coding: utf-8 -*-
"""
20. 결과 취합 — Claude에게 보낼 파일 만들기
- results/ 아래 모든 summary.md 를 순서대로 이어 붙여 results/00_DIGEST_for_Claude.md 생성
- 결과 폴더를 results_for_claude.zip 으로 압축(summary.md, 그림, 5MB 이하 CSV)
→ 이 두 파일만 대화창에 올려 주면 됩니다.
"""
import sys
import zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

import config as C

MAX_LINES_PER_REPORT = 400
MAX_CSV_MB = 5


def main():
    reps = sorted(p for p in C.RESULTS_DIR.glob("*/summary.md"))
    out = ["# TMS 분석 결과 모음(Claude 전달용)", "",
           f"- 생성: {pd.Timestamp.now():%Y-%m-%d %H:%M}",
           f"- 포함 보고서: {len(reps)}개", ""]
    out += ["## 목차", ""] + [f"- {p.parent.name}" for p in reps] + [""]
    for p in reps:
        lines = p.read_text(encoding="utf-8").splitlines()
        out += ["", "---", "", f"<!-- {p.parent.name} -->"]
        out += lines[:MAX_LINES_PER_REPORT]
        if len(lines) > MAX_LINES_PER_REPORT:
            out.append(f"\n_(이 보고서는 {len(lines)}줄 중 {MAX_LINES_PER_REPORT}줄만 포함)_")
        files = sorted(x.relative_to(p.parent).as_posix() for x in p.parent.rglob("*") if x.is_file() and x.name != "summary.md")
        out += ["", "산출 파일: " + ", ".join(files)]
    digest = C.RESULTS_DIR / "00_DIGEST_for_Claude.md"
    digest.write_text("\n".join(out), encoding="utf-8")
    print(f"[완료] {digest}")

    zpath = C.BASE_DIR / "results_for_claude.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in C.RESULTS_DIR.rglob("*"):
            if not f.is_file():
                continue
            if f.suffix.lower() == ".csv" and f.stat().st_size > MAX_CSV_MB * 1024 * 1024:
                continue
            z.write(f, f.relative_to(C.BASE_DIR))
    print(f"[완료] {zpath}  ({zpath.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
