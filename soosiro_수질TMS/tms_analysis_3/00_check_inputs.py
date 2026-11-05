# -*- coding: utf-8 -*-
"""
00. 입력 점검 — 표준 자료가 양식에 맞는지, 어떤 분석을 지금 돌릴 수 있는지 알려준다.   [항상 먼저]

- data/standard/ 의 표준 파일을 스키마로 검사(필수 열, 키 중복, 숫자형)
- data/meta/stations.csv 연결 정보 채움 현황
- 각 분석 스크립트 맨 위의 REQUIRES 를 읽어 '실행 가능 / 자료 대기' 표를 만든다
실행  python 00_check_inputs.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

import config as C
from core import Report, schema

LINKS = {"weather_link": "weather_stn", "flow_link": "flow_obscd", "tms_link": "upstream_tms", "stem": "stem"}


def main():
    rep = Report("00_check_inputs", "00. 입력 자료 점검", level="준비",
                 purpose="표준 자료의 형식을 검사하고, 지금 실행할 수 있는 분석과 자료를 기다리는 분석을 구분한다.")
    rows, have = [], set()
    for n, s in schema.SCHEMAS.items():
        f = s["file"]
        if not f.exists():
            rows.append({"양식": n, "파일": str(f.relative_to(C.BASE_DIR)), "상태": "없음", "행": 0, "검사": "-"})
            continue
        df = schema.read(n)
        issues = schema.validate(df, n)
        have.add(n)
        rows.append({"양식": n, "파일": str(f.relative_to(C.BASE_DIR)), "상태": "있음", "행": len(df),
                     "검사": "통과" if not issues else " / ".join(issues)})
    rep.h("1. 표준 자료")
    rep.table(pd.DataFrame(rows))

    if "stations" in have:
        st = schema.read("stations")
        for k, col in LINKS.items():
            if col in st and st[col].notna().any():
                have.add(k)
        if "tms_link" in have and not C.TMS_CLEAN_PKL.exists():
            have.discard("tms_link")
        rep.h("2. 측정소 연결표(data/meta/stations.csv)")
        rep.kv({f"{col} 입력된 측정소": int(st[col].notna().sum()) for col in LINKS.values() if col in st})
        rep.p("연결 정보 중 '추정'은 link_note 에 표시돼 있다. 측정소 좌표(lat/lon)를 받으면 tools/link_stations.py 로 가장 가까운 기상·유량 지점을 다시 계산할 수 있다.")
    if C.TMS_CLEAN_PKL.exists():
        have.add("tms")

    rep.h("3. 분석별 실행 가능 여부")
    plan = []
    for p in sorted(C.BASE_DIR.glob("[1-4][0-9]_*.py")):
        txt = p.read_text(encoding="utf-8")
        m = re.search(r"^REQUIRES\s*=\s*\[(.*?)\]", txt, re.M)
        req = re.findall(r"\"([^\"]+)\"", m.group(1)) if m else ["river_daily"]
        lv = re.search(r"^LEVEL\s*=\s*\"(.*?)\"", txt, re.M)
        miss = [r for r in req if r not in have]
        title = txt.split('"""')[1].strip().splitlines()[0] if '"""' in txt else p.stem
        plan.append({"스크립트": p.name, "단계": lv.group(1) if lv else "", "내용": title,
                     "필요": ", ".join(req), "상태": "실행 가능" if not miss else "자료 대기: " + ", ".join(miss)})
    t = pd.DataFrame(plan)
    rep.table(t, max_rows=80)
    ok = int((t["상태"] == "실행 가능").sum())
    rep.finding(f"분석 {len(t)}개 중 {ok}개 실행 가능, {len(t) - ok}개 자료 대기")
    for r in rows:
        if r["상태"] == "있음" and r["검사"] != "통과":
            rep.finding(f"⚠ {r['양식']} 형식 문제: {r['검사']}")
    rep.save()
    print(t[["스크립트", "상태"]].to_string(index=False))


if __name__ == "__main__":
    main()
