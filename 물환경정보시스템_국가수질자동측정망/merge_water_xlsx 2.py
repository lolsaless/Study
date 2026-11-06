# -*- coding: utf-8 -*-
"""
수질자동측정망 시간자료(xlsx) 병합기
- 실행하면 '병합할 폴더'를 고르는 창이 뜹니다(하위 폴더까지 포함해 모든 .xlsx 병합).
- 파일명 규칙: [하천_측정소]시간자료(YYYYMMDD-YYYYMMDD).xlsx  (예: [한강_가평]시간자료(20240101-20241231).xlsx)
- 결과(선택한 폴더 안 '병합결과' 폴더):
    merged_all.csv / merged_all.pkl : 하천·측정소·측정일시 + 항목별 측정값 (긴 형태, 1행 = 1시간)
    coverage_by_station.csv         : 측정소 × 항목 유효자료 비율 (ND/공란 제외)
    file_log.csv                    : 파일별 행수·기간·ND·공란·미측정 항목
    merge_report.txt                : 요약(중복, 파싱 실패, 기간 불일치 등)

실행:  python merge_water_xlsx.py            (폴더 선택 창)
       python merge_water_xlsx.py "/폴더/경로"  (경로 직접 지정)
필요 패키지: pandas, openpyxl
"""
import re
import sys
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

# ───────────── 설정 ─────────────
ND_TOKENS = {"ND", "N.D", "N.D.", "-", "--", "불검출", "미측정", "NA", "N/A", ""}
# 한 파일 안에서 어떤 항목의 (공란 제외) 값 중 ND 비율이 이 이상이면 '측정하지 않는 항목'으로 보고 전체를 제외
ND_DROP_RATIO = 0.5
# 병합 후 전 측정소에서 값이 하나도 없는 항목 열은 삭제
DROP_EMPTY_COLUMNS = True
OUT_DIRNAME = "병합결과"
FILE_RE = re.compile(r"\[(?P<river>[^_\]]+)_(?P<station>[^\]]+)\].*?\((?P<s>\d{8})-(?P<e>\d{8})\)")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


# ───────────── 폴더 선택 ─────────────
def pick_folder() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1]).expanduser()
    try:  # 1) tkinter
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        d = filedialog.askdirectory(title="병합할 xlsx 파일이 있는 폴더를 선택하세요")
        root.destroy()
        if d:
            return Path(d)
        sys.exit("폴더를 선택하지 않아 종료합니다.")
    except ImportError:
        pass
    if sys.platform == "darwin":  # 2) Homebrew Python 등 tkinter가 없을 때: macOS 기본 선택창
        r = subprocess.run(
            ["osascript", "-e", 'POSIX path of (choose folder with prompt "병합할 xlsx 폴더를 선택하세요")'],
            capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return Path(r.stdout.strip())
        sys.exit("폴더를 선택하지 않아 종료합니다.")
    return Path(input("병합할 폴더 경로를 입력하세요: ").strip().strip('"').strip("'")).expanduser()


# ───────────── 파일 1개 읽기 ─────────────
def read_one(path: Path, root: Path):
    """returns (DataFrame[하천,측정소,측정일시,항목...], 로그 dict)"""
    m = FILE_RE.search(path.name)
    river = m["river"] if m else (path.parent.name or "미상")
    station_fn = m["station"] if m else path.stem
    period = f"{m['s']}-{m['e']}" if m else ""

    raw = pd.read_excel(path, header=None, dtype=str, engine="openpyxl")
    # 머리글 행: 첫 칸이 '측정일'인 행. 데이터: 첫 칸이 날짜 형식인 행
    hdr = raw.index[raw.iloc[:, 0].astype(str).str.strip() == "측정일"]
    if len(hdr) == 0:
        raise ValueError("'측정일' 머리글 행을 찾지 못함")
    names = [re.sub(r"\s+", " ", str(x)).strip() for x in raw.iloc[hdr[0]].tolist()]
    body = raw[raw.iloc[:, 0].astype(str).str.match(DATE_RE)].copy()
    body.columns = names
    n_rows = len(body)

    dt = pd.to_datetime(body["측정일"].str.strip(), errors="coerce")
    n_bad_date = int(dt.isna().sum())
    body = body[dt.notna()].copy()
    body["측정일시"] = dt[dt.notna()]

    st_col = body["측정소명"].str.strip() if "측정소명" in body else pd.Series(station_fn, index=body.index)
    station = st_col.where(st_col.notna() & (st_col != ""), station_fn)

    items = [c for c in names if c not in ("측정일", "측정소명") and c != "nan"]
    out = pd.DataFrame({"하천": river, "측정소": station.values, "측정일시": body["측정일시"].values})
    log = {"파일": str(path.relative_to(root)), "하천": river, "측정소": station_fn, "파일명기간": period,
           "행수": n_rows, "날짜오류": n_bad_date,
           "실제기간": f"{body['측정일시'].min():%Y%m%d}-{body['측정일시'].max():%Y%m%d}" if len(body) else "",
           "ND항목": "", "미측정항목(ND위주)": "", "숫자변환실패": 0}
    nd_info, dropped, n_conv_fail = [], [], 0
    for c in items:
        s = body[c].astype(str).str.strip().where(body[c].notna(), "")
        is_nd = s.str.upper().isin({t.upper() for t in ND_TOKENS if t}) & (s != "")
        blank = s == ""
        num = pd.to_numeric(s.str.replace(",", "", regex=False), errors="coerce")
        conv_fail = num.isna() & ~is_nd & ~blank
        n_conv_fail += int(conv_fail.sum())
        n_nd, n_valid_or_nd = int(is_nd.sum()), int((~blank).sum())
        if n_nd:
            nd_info.append(f"{c}:{n_nd}")
        if n_valid_or_nd > 0 and n_nd / n_valid_or_nd >= ND_DROP_RATIO:
            dropped.append(c)
            num[:] = np.nan                      # 측정하지 않는 항목 → 이 측정소에서는 제외(NaN)
        num[is_nd] = np.nan                      # ND는 값이 아니므로 결측 처리
        out[c] = num.values
    log["ND항목"] = ", ".join(nd_info)
    log["미측정항목(ND위주)"] = ", ".join(dropped)
    log["숫자변환실패"] = n_conv_fail
    return out, log


# ───────────── 메인 ─────────────
def main():
    root = pick_folder()
    if not root.is_dir():
        sys.exit(f"폴더가 아닙니다: {root}")
    out_dir = root / OUT_DIRNAME
    files = sorted(p for p in root.rglob("*.xlsx")
                   if not p.name.startswith(("~$", "._")) and OUT_DIRNAME not in p.parts)
    print(f"[선택 폴더] {root}\n[xlsx 파일] {len(files)}개 발견")
    if not files:
        sys.exit("xlsx 파일이 없습니다.")

    frames, logs, errors = [], [], []
    for i, p in enumerate(files, 1):
        try:
            df, lg = read_one(p, root)
            frames.append(df)
            logs.append(lg)
            print(f"  ({i}/{len(files)}) {p.name}  {lg['행수']:,}행")
        except Exception as e:  # 한 파일이 깨져도 나머지는 계속
            errors.append(f"{p.name}: {e}")
            print(f"  ({i}/{len(files)}) {p.name}  [실패] {e}")
    if not frames:
        sys.exit("읽은 파일이 없습니다.")

    merged = pd.concat(frames, ignore_index=True, sort=False)
    key = ["하천", "측정소", "측정일시"]
    n_dup = int(merged.duplicated(key).sum())
    merged = merged.drop_duplicates(key, keep="first").sort_values(key).reset_index(drop=True)
    item_cols = [c for c in merged.columns if c not in key]
    empty_cols = [c for c in item_cols if merged[c].notna().sum() == 0]
    if DROP_EMPTY_COLUMNS and empty_cols:
        merged = merged.drop(columns=empty_cols)
        item_cols = [c for c in item_cols if c not in empty_cols]
    merged.insert(3, "연도", merged["측정일시"].dt.year)

    # 측정소 × 항목 유효자료 비율
    g = merged.groupby(["하천", "측정소"])
    cov = g[item_cols].apply(lambda x: (x.notna().mean() * 100).round(1)).reset_index()
    cov.insert(2, "행수", g.size().values)
    cov.insert(3, "시작", g["측정일시"].min().dt.strftime("%Y-%m-%d").values)
    cov.insert(4, "끝", g["측정일시"].max().dt.strftime("%Y-%m-%d").values)

    out_dir.mkdir(exist_ok=True)
    merged.to_csv(out_dir / "merged_all.csv", index=False, encoding="utf-8-sig")
    merged.to_pickle(out_dir / "merged_all.pkl")
    cov.to_csv(out_dir / "coverage_by_station.csv", index=False, encoding="utf-8-sig")
    flog = pd.DataFrame(logs)
    flog.to_csv(out_dir / "file_log.csv", index=False, encoding="utf-8-sig")

    # 보고서
    mismatch = flog[(flog["파일명기간"] != "") & (flog["파일명기간"] != flog["실제기간"])]
    lines = [
        "수질 시간자료 병합 보고서",
        f"폴더: {root}",
        f"읽은 파일: {len(frames)} / {len(files)}개",
        f"하천 {merged['하천'].nunique()}개, 측정소 {merged.groupby(['하천','측정소']).ngroups}개",
        f"기간: {merged['측정일시'].min():%Y-%m-%d} ~ {merged['측정일시'].max():%Y-%m-%d}",
        f"병합 행수: {len(merged):,} (중복 제거 {n_dup:,}행)",
        "연도별 행수: " + ", ".join(f"{y}:{n:,}" for y, n in merged["연도"].value_counts().sort_index().items()),
        f"전 측정소 값 없음으로 삭제한 열: {', '.join(empty_cols) if empty_cols else '없음'}",
        f"ND 위주(≥{ND_DROP_RATIO:.0%})라 제외한 (파일·항목): {int((flog['미측정항목(ND위주)'] != '').sum())}건 → file_log.csv 참조",
        f"파일명 기간과 실제 기간이 다른 파일: {len(mismatch)}개",
        f"날짜 변환 실패 행: {int(flog['날짜오류'].sum())}, 숫자 변환 실패 값: {int(flog['숫자변환실패'].sum())}",
    ]
    if len(mismatch):
        lines += ["  - " + r for r in mismatch["파일"].tolist()]
    if errors:
        lines += ["읽기 실패 파일:"] + ["  - " + e for e in errors]
    (out_dir / "merge_report.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n" + "\n".join(lines))
    print(f"\n[완료] 결과 폴더: {out_dir}")


if __name__ == "__main__":
    main()
