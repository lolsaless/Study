# -*- coding: utf-8 -*-
"""
새 자료 파일의 구조를 한눈에 출력 — 이 출력을 그대로 Claude 에게 붙여 넣으면 매핑(JSON)을 바로 만들 수 있다.

    python tools/peek.py data/inbox/어떤파일.csv
    python tools/peek.py data/inbox/어떤파일.xlsx --rows 20
    python tools/peek.py data/inbox/폴더/          (폴더 안 파일 목록 + 첫 파일 구조)

출력: 인코딩, 시트, 머리글 행 후보, 열 이름, 열별 예시 값·숫자 비율·날짜 형태 추정, 결측 표기 후보
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

DATE_PAT = [(r"^\d{4}-\d{2}-\d{2}$", "%Y-%m-%d"), (r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}", "%Y-%m-%d %H:%M"),
            (r"^\d{8}$", "%Y%m%d"), (r"^\d{10}$", "%Y%m%d%H"), (r"^\d{12}$", "%Y%m%d%H%M"),
            (r"^\d{4}\.\d{2}\.\d{2}", "%Y.%m.%d"), (r"^\d{4}/\d{2}/\d{2}", "%Y/%m/%d")]


def detect_encoding(p: Path):
    b = p.read_bytes()[:400000]
    if b[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "utf-16"
    b = b.rsplit(b"\n", 1)[0] if len(b) == 400000 else b     # 글자 중간에서 잘리지 않게
    for e in ["utf-8-sig", "cp949", "euc-kr"]:
        try:
            b.decode(e)
            return e
        except UnicodeDecodeError:
            continue
    return "unknown"


def raw_rows(p: Path, n: int):
    suf = p.suffix.lower()
    if suf in (".xlsx", ".xls", ".xlsm"):
        xl = pd.ExcelFile(p)
        print(f"시트: {xl.sheet_names}")
        return pd.read_excel(p, sheet_name=0, header=None, nrows=n + 30, dtype=str), None
    enc = detect_encoding(p)
    print(f"인코딩 추정: {enc}")
    head = p.read_bytes()[:3000].decode(enc if enc != "unknown" else "latin1", errors="replace")
    sep = max([",", "\t", ";", "|"], key=head.count)
    print(f"구분자 추정: {repr(sep)}")
    return pd.read_csv(p, header=None, nrows=n + 30, dtype=str, encoding=enc if enc != "unknown" else None,
                       sep=sep, on_bad_lines="skip", engine="python"), enc


def guess_header(raw: pd.DataFrame):
    """글자가 가장 많고 다음 행부터 숫자가 나오는 행을 머리글로 추정"""
    best, score = 0, -1
    for i in range(min(15, len(raw) - 1)):
        row = raw.iloc[i].dropna().astype(str)
        nxt = raw.iloc[i + 1].dropna().astype(str)
        txt = len({v for v in row if not re.fullmatch(r"[-\d.,: ]+", v)})   # 서로 다른 글자 칸 수
        num = sum(bool(re.fullmatch(r"[-\d.,: ]+", v)) for v in nxt)
        s = txt + num * 0.5
        if s > score:
            best, score = i, s
    return best


def profile(df: pd.DataFrame):
    rows = []
    for c in df.columns:
        s = df[c].dropna().astype(str).str.strip()
        s = s[s != ""]
        num = pd.to_numeric(s.str.replace(",", ""), errors="coerce")
        fmt = ""
        for pat, f in DATE_PAT:
            if len(s) and s.head(50).str.match(pat).mean() > 0.9:
                fmt = f
                break
        tokens = sorted(set(s[num.isna()].head(500)) - set(s.head(0)))[:6] if num.notna().mean() > 0.5 else []
        rows.append({"열": c, "예시": " | ".join(s.head(3)), "빈칸%": round((1 - len(s) / max(len(df), 1)) * 100),
                     "숫자%": round(num.notna().mean() * 100) if len(s) else 0, "날짜형식": fmt,
                     "숫자 아닌 값(결측표기 후보)": ", ".join(tokens)})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--rows", type=int, default=8)
    a = ap.parse_args()
    p = Path(a.path)
    if p.is_dir():
        files = sorted(x for x in p.rglob("*") if x.is_file())
        print(f"[폴더] {p} — 파일 {len(files)}개")
        for f in files[:30]:
            print(f"  {f.relative_to(p)}  ({f.stat().st_size / 1024:.0f} KB)")
        if not files:
            return
        p = files[0]
        print(f"\n첫 파일로 구조 확인: {p.name}")
    print(f"=== {p.name} ({p.stat().st_size / 1024:.0f} KB) ===")
    raw, enc = raw_rows(p, a.rows)
    print("\n[맨 위 원문 행(머리글 위치 확인용)]")
    print(raw.head(a.rows + 4).to_string(max_colwidth=18))
    h = guess_header(raw)
    print(f"\n머리글 행 추정: {h}번째 행(0부터) → 매핑의 read.header_row = {h}")
    body = raw.iloc[h + 1:].copy()
    cols = [str(x).strip() for x in raw.iloc[h]]
    body.columns = [c if cols.count(c) == 1 else f"{c}#{i}" for i, c in enumerate(cols)]   # 같은 이름 열 구분
    if (body.head(3).apply(lambda r: r.astype(str).str.fullmatch(r"[-\d.,: ]+").sum(), axis=1) == 0).any():
        print("※ 머리글 아래에 글자만 있는 행이 더 있다(2단 머리글) → 매핑의 read.skiprows 로 건너뛰세요")
    print(f"\n[열 프로필] (머리글 {h} 기준, 상위 {len(body)}행)")
    with pd.option_context("display.max_colwidth", 40, "display.width", 250):
        print(profile(body).to_string(index=False))
    print("\n다음 단계: python tools/make_mapping.py", a.path, "--target <표준양식>   (양식 목록: python -m core.schema)")


if __name__ == "__main__":
    main()
