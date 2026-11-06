"""tms_all_raw.csv 두 개 비교 (중복 값 · 행 수 차이의 원인 분석)

- 원본(A): 이 파일 옆 data/tms_all_raw.csv (또는 --original / --data-dir 로 지정)
- 비교(B): 실행하면 파일 선택 창이 뜹니다. (--other 경로 로 직접 지정도 가능)
- 두 파일의 이름이 같아도 문제없습니다. 항상 '원본(A)' / '비교(B)' 로 구분하고,
  결과는 data/compare_날짜시각/ 새 폴더에만 저장하므로 어떤 파일도 덮어쓰지 않습니다.
  (같은 파일을 A, B 로 중복 선택하면 알려주고 멈춥니다.)

비교 기준 키: 연도 + 일자 + 사업장명 + 방류구  (순번은 수집 순서라 비교에서 제외)

결과 폴더:
    summary.txt        요약(행 수 차이의 원인 분해 포함)
    dup_A.csv, dup_B.csv   각 파일 안의 키 중복 행
    only_in_A.csv, only_in_B.csv   한쪽에만 있는 행
    value_diff.csv     양쪽에 있으나 측정값이 다른 행
    site_quarter_diff.csv   사업장×분기별 행 수 비교(차이 나는 곳만)

사용:
    python soosiro_compare_raw.py
    python soosiro_compare_raw.py --other "D:/다른폴더/tms_all_raw.csv"
    python soosiro_compare_raw.py --original "경로/A.csv" --other "경로/B.csv"
"""
import argparse
import os
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd

KEY_COLS = ["연도", "일자", "사업장명", "방류구"]
VALUE_COLS = [
    "pH_측정값", "TOC_측정값", "TOC_배출량", "SS_측정값", "SS_배출량",
    "TN_측정값", "TN_배출량", "TP_측정값", "TP_배출량",
]


def say(msg=""):
    print(msg, flush=True)


def fix_console_encoding():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors="replace")
        except Exception:
            pass


# ── 파일 선택 ─────────────────────────────────────────────────────────
def pick_file(title, initial_dir):
    """선택 창(tkinter) → 안 되면 경로 직접 입력. 취소하면 None."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        p = filedialog.askopenfilename(
            title=title, initialdir=str(initial_dir),
            filetypes=[("CSV 파일", "*.csv"), ("모든 파일", "*.*")])
        root.destroy()
        return Path(p) if p else None
    except Exception:
        try:
            s = input(f"{title}\n  파일 경로를 입력(붙여넣기)하세요 (엔터=취소): ").strip().strip('"').strip("'")
        except EOFError:
            return None
        return Path(s) if s else None


# ── 읽기·정규화 ───────────────────────────────────────────────────────
def read_csv_auto(path):
    last = None
    for enc in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(path, dtype=str, encoding=enc)
        except Exception as e:
            last = e
    raise last


def norm_value(v):
    """'1' 과 '1.0', 공백 차이 등을 같은 값으로 취급. 'p' 표시 등 문자는 그대로 비교."""
    if pd.isna(v):
        return ""
    s = unicodedata.normalize("NFC", str(v)).strip().replace(",", "")
    if s in ("", "-", "–"):
        return ""
    try:
        return repr(float(s))
    except ValueError:
        return s


def load(path, label):
    df = read_csv_auto(path)
    df.columns = [unicodedata.normalize("NFC", str(c)).strip().lstrip("\ufeff") for c in df.columns]
    miss = [c for c in KEY_COLS if c not in df.columns]
    if miss:
        raise ValueError(f"{label} 파일에 필수 열이 없습니다: {miss} (tms_all_raw.csv 가 맞는지 확인하세요)")
    for c in KEY_COLS + [c for c in VALUE_COLS if c in df.columns]:
        df[c] = df[c].map(lambda v: "" if pd.isna(v) else unicodedata.normalize("NFC", str(v)).strip())
    df["_행번호"] = range(2, len(df) + 2)  # 엑셀/CSV 기준 행 번호(1행=헤더)
    df["_키"] = df[KEY_COLS].agg("|".join, axis=1)
    return df


def save(df, path):
    df.to_csv(path, index=False, encoding="utf-8-sig")


def describe(p):
    p = Path(p)
    try:
        st = p.stat()
        return f"{p}  ({st.st_size / 1024 / 1024:.1f} MB, 수정 {datetime.fromtimestamp(st.st_mtime):%Y-%m-%d %H:%M})"
    except OSError:
        return str(p)


# ── 비교 ──────────────────────────────────────────────────────────────
def compare(path_a, path_b, out_root):
    A, B = load(path_a, "원본(A)"), load(path_b, "비교(B)")
    out = Path(out_root) / f"compare_{datetime.now():%Y%m%d_%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    L = []  # summary lines

    def w(s=""):
        L.append(s)
        say(s)

    w("=== tms_all_raw.csv 비교 ===")
    w(f"원본(A): {describe(path_a)}")
    w(f"비교(B): {describe(path_b)}")
    w(f"행 수  : A {len(A):,}행 / B {len(B):,}행 / 차이(A-B) {len(A) - len(B):+,}")
    for lab, d in (("A", A), ("B", B)):
        w(f"  {lab}: 사업장 {d['사업장명'].nunique():,}곳, 기간 {d['연도'].min()}~{d['연도'].max()}")

    # 1) 파일 내부 중복
    dupA = A[A.duplicated("_키", keep=False)].sort_values(["_키", "_행번호"])
    dupB = B[B.duplicated("_키", keep=False)].sort_values(["_키", "_행번호"])
    extraA = int(A.duplicated("_키").sum())
    extraB = int(B.duplicated("_키").sum())
    fullA = int(A.drop(columns=["_행번호"]).duplicated().sum())
    fullB = int(B.drop(columns=["_행번호"]).duplicated().sum())
    w("")
    w("[1] 각 파일 안의 중복 (같은 연도·일자·사업장·방류구)")
    w(f"  A: 초과(중복) 행 {extraA:,}개 / 그중 순번까지 모든 열이 같은 행 {fullA:,}개")
    w(f"  B: 초과(중복) 행 {extraB:,}개 / 그중 순번까지 모든 열이 같은 행 {fullB:,}개")
    if len(dupA):
        save(dupA.drop(columns=["_키"]), out / "dup_A.csv")
    if len(dupB):
        save(dupB.drop(columns=["_키"]), out / "dup_B.csv")
    if extraA or extraB:
        top = pd.concat([dupA.assign(파일="A"), dupB.assign(파일="B")])
        t = top.groupby(["파일", "사업장명"]).size().sort_values(ascending=False).head(10)
        w("  중복 행이 많은 사업장 상위: " + ", ".join(f"{a}-{b}({n})" for (a, b), n in t.items()))

    # 2) 키 기준 비교 (중복은 마지막 행만 사용)
    Au = A.drop_duplicates("_키", keep="last").set_index("_키")
    Bu = B.drop_duplicates("_키", keep="last").set_index("_키")
    ka, kb = set(Au.index), set(Bu.index)
    onlyA, onlyB, both = sorted(ka - kb), sorted(kb - ka), sorted(ka & kb)
    w("")
    w("[2] 키 기준 비교 (중복은 마지막 행 1개로 계산)")
    w(f"  A와 B 모두에 있음 {len(both):,} / A에만 있음 {len(onlyA):,} / B에만 있음 {len(onlyB):,}")
    if onlyA:
        save(Au.loc[onlyA].reset_index(drop=True).drop(columns=[]), out / "only_in_A.csv")
    if onlyB:
        save(Bu.loc[onlyB].reset_index(drop=True), out / "only_in_B.csv")

    # 3) 같은 키의 값 차이
    vcols = [c for c in VALUE_COLS if c in Au.columns and c in Bu.columns]
    ndiff = 0
    if both and vcols:
        a_n = Au.loc[both, vcols].apply(lambda s: s.map(norm_value))
        b_n = Bu.loc[both, vcols].apply(lambda s: s.map(norm_value))
        neq = (a_n != b_n)
        rows = neq.any(axis=1)
        ndiff = int(rows.sum())
        if ndiff:
            recs = []
            for k in neq.index[rows]:
                cols = [c for c in vcols if neq.at[k, c]]
                r = {c: Au.at[k, c] for c in KEY_COLS}
                r["A_행번호"], r["B_행번호"] = Au.at[k, "_행번호"], Bu.at[k, "_행번호"]
                r["다른열"] = ", ".join(cols)
                for c in cols:
                    r[f"{c}_A"], r[f"{c}_B"] = Au.at[k, c], Bu.at[k, c]
                recs.append(r)
            save(pd.DataFrame(recs), out / "value_diff.csv")
    w("")
    w("[3] 양쪽에 있는 행 중 측정값이 다른 행")
    w(f"  {ndiff:,}행" + (" → value_diff.csv" if ndiff else " (모두 같음)"))

    # 4) 행 수 차이 원인 분해
    diff = len(A) - len(B)
    w("")
    w("[4] 행 수 차이(A-B)의 원인")
    w(f"  A만 있는 행 {len(onlyA):,} - B만 있는 행 {len(onlyB):,} = {len(onlyA) - len(onlyB):+,}")
    w(f"  A의 중복 초과 {extraA:,} - B의 중복 초과 {extraB:,} = {extraA - extraB:+,}")
    calc = (len(onlyA) - len(onlyB)) + (extraA - extraB)
    w(f"  합계 {calc:+,}  (실제 차이 {diff:+,}) → {'일치' if calc == diff else '불일치(확인 필요)'}")
    if diff == 0 and not (onlyA or onlyB or extraA or extraB or ndiff):
        w("  → 두 파일은 (순번을 제외하면) 완전히 같은 내용입니다.")

    # 5) 사업장×분기 행 수
    def cnt(d, lab):
        return d.groupby(["사업장명", "연도", "분기"] if "분기" in d.columns else ["사업장명", "연도"]).size().rename(lab)
    sq = pd.concat([cnt(A, "A_행수"), cnt(B, "B_행수")], axis=1).fillna(0).astype(int)
    sq["차이(A-B)"] = sq["A_행수"] - sq["B_행수"]
    sqd = sq[sq["차이(A-B)"] != 0].reset_index().sort_values("차이(A-B)", key=lambda s: s.abs(), ascending=False)
    w("")
    w("[5] 사업장×분기별 행 수가 다른 곳")
    w(f"  {len(sqd):,}곳" + (" → site_quarter_diff.csv (상위 10건 아래)" if len(sqd) else ""))
    if len(sqd):
        save(sqd, out / "site_quarter_diff.csv")
        for _, r in sqd.head(10).iterrows():
            tag = " / ".join(str(r[c]) for c in sqd.columns[:-3])
            w(f"   - {tag}: A {r['A_행수']:,} / B {r['B_행수']:,} ({r['차이(A-B)']:+,})")

    (out / "summary.txt").write_text("\n".join(L) + "\n", encoding="utf-8-sig")
    w("")
    w(f"결과 저장 폴더: {out}")
    return out


def main():
    fix_console_encoding()
    ap = argparse.ArgumentParser(description="tms_all_raw.csv 두 파일 비교")
    ap.add_argument("--data-dir", default=None, help="원본이 있는 data 폴더 (기본: 이 파일 옆의 data/)")
    ap.add_argument("--original", default=None, help="원본(A) 파일 경로 (기본: data/tms_all_raw.csv)")
    ap.add_argument("--other", default=None, help="비교(B) 파일 경로 (생략하면 선택 창)")
    a = ap.parse_args()

    data_dir = Path(a.data_dir) if a.data_dir else Path(__file__).resolve().parent / "data"
    path_a = Path(a.original) if a.original else data_dir / "tms_all_raw.csv"
    if not path_a.is_file():
        say(f"[오류] 원본(A) 파일이 없습니다: {path_a}")
        say("  --data-dir 또는 --original 로 위치를 지정해 주세요.")
        sys.exit(1)

    path_b = Path(a.other) if a.other else pick_file("비교할 tms_all_raw.csv 선택 (비교 대상 B)", data_dir.parent)
    if not path_b:
        say("파일을 선택하지 않아 종료합니다.")
        sys.exit(1)
    if not path_b.is_file():
        say(f"[오류] 비교(B) 파일을 찾을 수 없습니다: {path_b}")
        sys.exit(1)
    try:
        same = os.path.samefile(path_a, path_b)
    except OSError:
        same = path_a.resolve() == path_b.resolve()
    if same:
        say("[중단] 원본(A)과 비교(B)가 같은 파일입니다. 다른 폴더의 파일을 선택하세요.")
        say(f"  {path_a.resolve()}")
        sys.exit(1)

    try:
        compare(path_a, path_b, data_dir)
    except Exception as e:
        say(f"[오류] 비교 중 문제가 생겼습니다: {type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
