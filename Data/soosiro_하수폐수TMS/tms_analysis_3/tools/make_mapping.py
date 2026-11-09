# -*- coding: utf-8 -*-
"""
매핑 초안 자동 생성 — 원본 열 이름을 표준 열 이름으로 '추정'해 ingest/mappings/<이름>.json 을 만든다.

    python tools/make_mapping.py data/inbox/kma_aws/aws_2026.csv --target weather_daily
    python tools/make_mapping.py data/inbox/wamis/ --target flow_daily --name wamis_flow
    python tools/make_mapping.py data/inbox/수질.xlsx --target river_hourly --print   (저장 없이 출력)

그다음: 초안을 열어 '???' 와 추정값을 확인 → python ingest/mapper.py ingest/mappings/<이름>.json --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tools"))
from core import schema  # noqa: E402
from peek import raw_rows, guess_header, DATE_PAT  # noqa: E402

# 표준 열 ← 원본 열 이름에 흔히 들어가는 글자(앞쪽이 우선)
SYNONYMS = {
    "basin": ["수계", "권역", "대권역", "하천"],
    "station": ["측정소명", "측정소", "지점명", "관측소명"],
    "datetime": ["측정일시", "측정일", "일시", "시각", "datetime", "msrDate", "MSR_DATE"],
    "date": ["일자", "날짜", "일시", "측정일", "관측일", "date", "ymd", "time"],
    "stn": ["지점번호", "지점코드", "지점", "stnId", "stn"],
    "stn_name": ["지점명", "stnNm"],
    "rain_mm": ["일강수량", "강수량", "강우량", "rn", "sumRn", "rf"],
    "ta_mean": ["평균기온", "avgTa", "기온"],
    "ta_min": ["최저기온", "minTa"],
    "ta_max": ["최고기온", "maxTa"],
    "obscd": ["관측소코드", "관측소번호", "wlobscd", "obscd", "코드"],
    "obs_name": ["관측소명", "obsnm"],
    "wl_m": ["수위", "wl"],
    "flow_cms": ["유량", "fw", "flow", "Q(m3/s)"],
    "code": ["코드", "지점번호", "code"],
    "name": ["이름", "지점명", "관측소명", "name"],
    "lat": ["위도", "lat", "Y좌표"],
    "lon": ["경도", "lon", "lng", "X좌표"],
    "address": ["주소", "소재지", "addr"],
    "WT": ["수온"], "pH": ["수소이온", "pH"], "EC": ["전기전도도", "EC"], "DO": ["용존산소", "DO"],
    "Turb": ["탁도"], "TOC": ["총유기탄소", "TOC"], "TN": ["총질소", "T-N", "TN"], "TP": ["총인", "T-P", "TP"],
    "Chl_a": ["클로로필", "Chl"], "NH3_N": ["암모니아"], "NO3_N": ["질산"], "PO4_P": ["인산염"],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--target", required=True, choices=list(schema.SCHEMAS))
    ap.add_argument("--name")
    ap.add_argument("--print", action="store_true")
    a = ap.parse_args()
    p = Path(a.path)
    first = sorted(x for x in p.rglob("*") if x.is_file())[0] if p.is_dir() else p
    raw, enc = raw_rows(first, 5)
    h = guess_header(raw)
    cols = [str(x).strip() for x in raw.iloc[h]]
    body = raw.iloc[h + 1:h + 40]
    tgt = schema.SCHEMAS[a.target]["columns"]
    mapping, used = {}, set()
    for std in tgt:
        base = std.rsplit("_", 1)[0] if a.target == "river_daily" and std.endswith(("_mean", "_min", "_max", "_med", "_n")) else std
        for syn in SYNONYMS.get(std, SYNONYMS.get(base, [])):
            hit = [c for c in cols if c not in used and syn.lower() in c.lower()]
            if hit:
                mapping[hit[0]] = std
                used.add(hit[0])
                break
    dt = None
    for src, std in mapping.items():
        if std in ("datetime", "date"):
            vals = body.iloc[:, cols.index(src)].dropna().astype(str).str.strip()
            for pat, f in DATE_PAT:
                if len(vals) and vals.str.match(pat).mean() > 0.9:
                    dt = {"col": std, "format": f, "ymdh": f.endswith("%H") and not f.endswith(":%M")}
    d = (p if p.is_dir() else p.parent).resolve()
    rel = d.relative_to(BASE) if str(d).startswith(str(BASE)) else d
    glob_pat = f"{rel.as_posix()}/*{first.suffix}"
    req_missing = [c for c, (t, req, *_r) in tgt.items() if req and c not in mapping.values()]
    m = {
        "_설명": f"자동 생성 초안({first.name}). '???' 와 추정값을 확인하세요",
        "target": a.target,
        "inputs": [glob_pat],
        "read": {"encoding": enc or "auto", "header_row": int(h)},
        "columns": mapping,
        "datetime": dt,
        "constants": {c: "???" for c in req_missing},
        "_확인필요_필수열": req_missing,
        "_매핑안된_원본열": [c for c in cols if c not in used],
        "fillna": {},
        "scale": {},
        "auto": False,
    }
    txt = json.dumps(m, ensure_ascii=False, indent=1)
    if a.print:
        print(txt)
        return
    out = BASE / "ingest" / "mappings" / f"{a.name or re.sub(r'[^0-9A-Za-z가-힣_]+', '_', first.stem)}.json"
    out.write_text(txt, encoding="utf-8")
    print(txt)
    print(f"\n[저장] {out.relative_to(BASE)}\n확인 후: python ingest/mapper.py {out.relative_to(BASE)} --dry-run")


if __name__ == "__main__":
    main()
