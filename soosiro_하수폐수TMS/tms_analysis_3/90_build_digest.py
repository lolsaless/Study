# -*- coding: utf-8 -*-
"""
90. 결과 취합 — ① results/00_핵심결과.md (모든 분석의 '핵심 결과'만 단계별로)  ② results/00_DIGEST_for_Claude.md (전체 보고서)
                ③ results_for_claude.zip (summary·그림·5MB 이하 CSV)
→ 새 대화에서 Claude 에게는 작업안내서.md + 00_핵심결과.md (+ 필요하면 DIGEST·zip) 를 주면 된다.
"""
import json
import sys
import zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

import config as C

ORDER = {"0": "준비", "1": "기본", "2": "중급", "3": "심화", "4": "연계"}
MAX_LINES = 300
MAX_CSV_MB = 5


def main():
    reps = sorted(p for p in C.RESULTS_DIR.glob("[0-9][0-9]_*/summary.md"))
    now = f"{pd.Timestamp.now():%Y-%m-%d %H:%M}"
    key = ["# 핵심 결과 요약(자동 생성)", "", f"- 생성: {now} · 보고서 {len(reps)}개", "- 각 줄의 근거는 results/<번호>/summary.md", ""]
    waiting = []
    cur = None
    for p in reps:
        fj = p.parent / "findings.json"
        info = json.loads(fj.read_text(encoding="utf-8")) if fj.exists() else {"title": p.parent.name, "findings": [], "status": "?"}
        stage = ORDER.get(p.parent.name[0], "기타")
        if stage != cur:
            key += ["", f"## {stage}", ""]
            cur = stage
        if info.get("status") == "자료 대기":
            waiting.append(info["title"])
            key.append(f"### {info['title']} — ⏳ 자료 대기")
            continue
        key.append(f"### {info['title']}")
        key += [f"- {t}" for t in info.get("findings", [])] or ["- (핵심 결과 없음 — summary.md 참고)"]
    if waiting:
        key += ["", "## 자료 대기 중인 분석", ""] + [f"- {w}" for w in waiting]
    (C.RESULTS_DIR / "00_핵심결과.md").write_text("\n".join(key), encoding="utf-8")

    out = ["# tms_analysis_3 결과 모음(Claude 전달용)", "", f"- 생성: {now}", f"- 포함 보고서: {len(reps)}개", "",
           "## 목차", ""] + [f"- {p.parent.name}" for p in reps] + [""]
    for p in reps:
        lines = p.read_text(encoding="utf-8").splitlines()
        out += ["", "---", "", f"<!-- {p.parent.name} -->"] + lines[:MAX_LINES]
        if len(lines) > MAX_LINES:
            out.append(f"\n_(이 보고서는 {len(lines)}줄 중 {MAX_LINES}줄만 포함)_")
    (C.RESULTS_DIR / "00_DIGEST_for_Claude.md").write_text("\n".join(out), encoding="utf-8")
    zpath = C.BASE_DIR / "results_for_claude.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in C.RESULTS_DIR.rglob("*"):
            if f.is_file() and not (f.suffix == ".csv" and f.stat().st_size > MAX_CSV_MB * 1024 * 1024):
                z.write(f, f.relative_to(C.BASE_DIR))
    print(f"[완료] {C.RESULTS_DIR / '00_핵심결과.md'}")
    print(f"[완료] {C.RESULTS_DIR / '00_DIGEST_for_Claude.md'}")
    print(f"[완료] {zpath} ({zpath.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
