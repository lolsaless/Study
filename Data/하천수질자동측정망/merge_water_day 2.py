# -*- coding: utf-8 -*-
"""
수질자동측정망 시간자료(xlsx) → 권역별 '일별' 통계 데이터 (merge_water_day.py)

[하는 일]
1. 폴더를 고르면 하위 폴더까지 모든 .xlsx(시간자료)를 읽는다.
   파일명 규칙: [권역_측정소]시간자료(YYYYMMDD-YYYYMMDD).xlsx   예) [한강_가평]시간자료(20240101-20241231).xlsx
2. ND·공란은 결측으로 처리하고, ND 위주인 항목(측정하지 않는 항목)은 그 측정소에서 제외한다.
3. 권역(한강·금강·낙동강·영산강)별로 연도 구분 없이 합친 뒤, 측정소별 '하루' 단위로 변수마다
   평균(mean)·최소(min)·최대(max)·중앙값(med)·유효 시간수(n)를 계산한다.
4. 권역 하나가 끝날 때마다 즉시 Data 폴더에 저장한다.

[결과: 선택한 폴더 안 Data/]
  한강_일별.csv / .pkl ...   1행 = 1측정소 × 1일 (분석용 본 파일)
  한강_커버리지.csv ...      측정소 × 변수별 '자료가 있는 날'의 비율(%)
  데이터_설명.md             컬럼 설명서 (Claude에게 분석을 맡길 때 이 파일을 함께 올리면 됨)
  file_log.csv, merge_report.txt   처리 기록

[컬럼 이름 규칙]  <변수코드>_<통계>   예) TN_mean, TN_min, TN_max, TN_med, TN_n
  통계: mean 평균 / min 최소 / max 최대 / med 중앙값 / n 그날 유효(값이 있는) 시간 수(0~24)

필요 패키지: pandas, openpyxl
실행:  python merge_water_day.py            (폴더 선택 창)
       python merge_water_day.py "/폴더/경로"
"""
import re
import sys
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

# ───────────── 변수 코드표 (한글 항목명 앞부분으로 매칭) ─────────────
VAR_MAP = {
    "수온": ("WT", "수온", "℃"),
    "수소이온농도": ("pH", "수소이온농도", "-"),
    "전기전도도": ("EC", "전기전도도", "μS/cm"),
    "용존산소": ("DO", "용존산소", "mg/L"),
    "탁도": ("Turb", "탁도", "NTU"),
    "총유기탄소": ("TOC", "총유기탄소", "mg/L"),
    "총질소": ("TN", "총질소", "mg/L"),
    "총인": ("TP", "총인", "mg/L"),
    "클로로필-a": ("Chl_a", "클로로필-a", "mg/㎥"),
}
STATS = [("mean", "평균"), ("min", "최소"), ("max", "최대"), ("median", "중앙값"), ("count", "유효시간수")]
STAT_SUFFIX = {"mean": "mean", "min": "min", "max": "max", "median": "med", "count": "n"}


def code_of(col: str):
    """원본 열 이름 → (코드, 한글명, 단위)"""
    base = re.sub(r"\s*\(.*\)\s*$", "", col).strip()
    unit_m = re.search(r"\((.*)\)", col)
    if base in VAR_MAP:
        return VAR_MAP[base]
    return (re.sub(r"\W+", "_", base), base, unit_m.group(1) if unit_m else "")


# ───────────── 설정 ─────────────
ND_TOKENS = {"ND", "N.D", "N.D.", "-", "--", "불검출", "미측정", "NA", "N/A", ""}
# 한 파일 안에서 어떤 항목의 (공란 제외) 값 중 ND 비율이 이 이상이면 '측정하지 않는 항목'으로 보고 전체를 제외
ND_DROP_RATIO = 0.5
# 권역 안 전 측정소에서 값이 하나도 없는 항목 열은 삭제
DROP_EMPTY_COLUMNS = True
OUT_DIRNAME = "Data"      # 선택한 폴더 안에 만들어질 저장 폴더 이름
SAVE_HOURLY = False       # True면 권역별 시간자료(통합)도 함께 저장 (용량 큼)
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


# ───────────── 일별 변환 ─────────────
def to_daily(hourly: pd.DataFrame):
    """시간자료(하천,측정소,측정일시,항목...) → 측정소×일 통계표. returns (daily, var_info)"""
    items = [c for c in hourly.columns if c not in ("하천", "측정소", "측정일시")]
    info = {}  # 코드 -> (한글명, 단위)
    rename = {}
    for c in items:
        code, kor, unit = code_of(c)
        rename[c] = code
        info[code] = (kor, unit)
    h = hourly.rename(columns=rename)
    h["날짜"] = h["측정일시"].dt.normalize()
    codes = list(info)
    g = h.groupby(["하천", "측정소", "날짜"])
    agg = g[codes].agg([s for s, _ in STATS])
    # 변수별로 mean,min,max,med,n 순서가 되도록 열 정렬 + 이름 평탄화
    agg = agg.reindex(columns=pd.MultiIndex.from_product([codes, [s for s, _ in STATS]]))
    agg.columns = [f"{c}_{STAT_SUFFIX[s]}" for c, s in agg.columns]
    for c in agg.columns:
        if not c.endswith("_n"):
            agg[c] = agg[c].round(4)
    daily = agg.reset_index()
    daily.insert(3, "연도", daily["날짜"].dt.year)
    daily.insert(4, "월", daily["날짜"].dt.month)
    daily["날짜"] = daily["날짜"].dt.strftime("%Y-%m-%d")
    daily.insert(5, "시간기록수", g.size().values)   # 그날 시간자료 행 수(보통 24)
    return daily, info


def write_doc(out_dir: Path, summaries: list, var_info: dict):
    L = ["# 수질자동측정망 일별 통계 데이터 설명서", "",
         "이 폴더의 `*_일별.csv`는 수질자동측정망 **시간자료를 측정소별 하루 단위로 요약**한 것입니다.", "",
         "## 파일 구조", "- 권역(수계)별 1개 파일: 한강·금강·낙동강·영산강, 여러 연도가 한 파일에 들어 있음",
         "- **1행 = 1측정소 × 1일**", "",
         "## 컬럼", "| 컬럼 | 설명 |", "|---|---|",
         "| 하천 | 권역(수계) 이름 |", "| 측정소 | 측정소 이름 |", "| 날짜 | YYYY-MM-DD |",
         "| 연도, 월 | 날짜에서 뽑은 값 |", "| 시간기록수 | 그날 시간자료 행 수(정상이면 24) |",
         "| `<코드>_mean / _min / _max / _med` | 그날 시간값들의 평균 / 최솟값 / 최댓값 / 중앙값 |",
         "| `<코드>_n` | 그날 값이 실제로 있는 시간 수(0~24). 신뢰도 판단용 |", "",
         "## 변수 코드", "| 코드 | 항목 | 단위 |", "|---|---|---|"]
    for code, (kor, unit) in var_info.items():
        L.append(f"| {code} | {kor} | {unit} |")
    L += ["", "## 처리 규칙", "- 원자료의 `ND`(불검출)와 빈칸은 **값이 아니라 결측(NaN)** 으로 처리했습니다. 0으로 바꾸지 않았습니다.",
          "- 어떤 측정소에서 한 항목이 ND 위주(50% 이상)이면 그 측정소의 해당 항목은 측정하지 않는 것으로 보고 전부 결측입니다.",
          "- 하루 중 값이 하나도 없으면 `_mean/_min/_max/_med`는 빈칸, `_n`은 0입니다.",
          "- 통계는 값이 있는 시간만으로 계산했습니다. `_n`이 작은 날(예: 12시간 미만)은 하루를 대표하지 못할 수 있으니 분석 목적에 맞게 `_n` 기준으로 걸러 쓰세요.",
          "- 같은 측정소·같은 시각이 중복되면 첫 번째 값만 사용했습니다.", "",
          "## 권역별 요약"]
    L += [f"- {s}" for s in summaries]
    (out_dir / "데이터_설명.md").write_text("\n".join(L), encoding="utf-8")


# ───────────── 메인 ─────────────
def river_of(p: Path) -> str:
    m = FILE_RE.search(p.name)
    return m["river"] if m else (p.parent.name or "미상")


def main():
    root = pick_folder()
    if not root.is_dir():
        sys.exit(f"폴더가 아닙니다: {root}")
    out_dir = root / OUT_DIRNAME
    out_dir.mkdir(exist_ok=True)
    files = sorted(p for p in root.rglob("*.xlsx")
                   if not p.name.startswith(("~$", "._")) and OUT_DIRNAME not in p.parts)
    print(f"[선택 폴더] {root}\n[저장 폴더] {out_dir}\n[xlsx 파일] {len(files)}개 발견")
    if not files:
        sys.exit("xlsx 파일이 없습니다.")

    by_river = {}
    for p in files:
        by_river.setdefault(river_of(p), []).append(p)
    print("[권역별 파일 수] " + ", ".join(f"{r}:{len(v)}" for r, v in by_river.items()))

    all_logs, errors, summary, var_info_all = [], [], [], {}
    for river, plist in by_river.items():
        print(f"\n=== {river} ({len(plist)}개 파일) ===")
        frames = []
        for i, p in enumerate(plist, 1):
            try:
                df, lg = read_one(p, root)
                frames.append(df)
                all_logs.append(lg)
                pd.DataFrame(all_logs).to_csv(out_dir / "file_log.csv", index=False, encoding="utf-8-sig")
                print(f"  ({i}/{len(plist)}) {p.name}  {lg['행수']:,}행")
            except Exception as e:  # 한 파일이 깨져도 나머지는 계속
                errors.append(f"{p.name}: {e}")
                print(f"  ({i}/{len(plist)}) {p.name}  [실패] {e}")
        if not frames:
            continue

        hourly = pd.concat(frames, ignore_index=True, sort=False)
        del frames
        key = ["측정소", "측정일시"]
        n_dup = int(hourly.duplicated(key).sum())
        hourly = hourly.drop_duplicates(key, keep="first").sort_values(key).reset_index(drop=True)
        item_cols = [c for c in hourly.columns if c not in ("하천", "측정소", "측정일시")]
        empty_cols = [c for c in item_cols if hourly[c].notna().sum() == 0]
        if DROP_EMPTY_COLUMNS and empty_cols:
            hourly = hourly.drop(columns=empty_cols)
        n_hourly = len(hourly)
        if SAVE_HOURLY:
            hourly.to_pickle(out_dir / f"{river}_시간통합.pkl")

        daily, info = to_daily(hourly)
        del hourly
        var_info_all.update(info)

        # 커버리지: 측정소 × 변수, '값이 있는 날'의 비율(%)
        ncols = [c for c in daily.columns if c.endswith("_n")]
        cov = (daily[ncols] > 0).groupby(daily["측정소"]).mean().mul(100).round(1)
        cov.columns = [c[:-2] for c in ncols]
        cov.insert(0, "일수", daily.groupby("측정소").size())
        cov = cov.reset_index()

        # ── 즉시 저장 ──
        daily.to_csv(out_dir / f"{river}_일별.csv", index=False, encoding="utf-8-sig")
        daily.to_pickle(out_dir / f"{river}_일별.pkl")
        cov.to_csv(out_dir / f"{river}_커버리지.csv", index=False, encoding="utf-8-sig")
        yrs = ", ".join(f"{y}:{n:,}" for y, n in daily["연도"].value_counts().sort_index().items())
        line = (f"**{river}**: 측정소 {daily['측정소'].nunique()}개, 일별 {len(daily):,}행 "
                f"({daily['날짜'].min()}~{daily['날짜'].max()}), 연도별 일수 [{yrs}], "
                f"원 시간자료 {n_hourly:,}행(중복 제거 {n_dup:,}행), 삭제한 빈 항목: {', '.join(empty_cols) or '없음'}")
        summary.append(line)
        write_doc(out_dir, summary, var_info_all)
        print(f"  → 저장 완료: {out_dir / (river + '_일별.csv')}\n  {line}")
        del daily, cov

    flog = pd.DataFrame(all_logs)
    mismatch = flog[(flog["파일명기간"] != "") & (flog["파일명기간"] != flog["실제기간"])] if len(flog) else flog
    lines = ["수질 일별 변환 보고서", f"폴더: {root}", f"읽은 파일: {len(all_logs)} / {len(files)}개", ""]
    lines += [s.replace("**", "") for s in summary]
    lines += ["", f"ND 위주(≥{ND_DROP_RATIO:.0%})라 제외한 (파일·항목): "
              f"{int((flog['미측정항목(ND위주)'] != '').sum()) if len(flog) else 0}건 → file_log.csv 참조",
              f"파일명 기간과 실제 기간이 다른 파일: {len(mismatch)}개"]
    lines += ["  - " + r for r in mismatch["파일"].tolist()] if len(mismatch) else []
    if len(flog):
        lines.append(f"날짜 변환 실패 행: {int(flog['날짜오류'].sum())}, 숫자 변환 실패 값: {int(flog['숫자변환실패'].sum())}")
    if errors:
        lines += ["읽기 실패 파일:"] + ["  - " + e for e in errors]
    (out_dir / "merge_report.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n" + "\n".join(lines))
    print(f"\n[완료] 결과 폴더: {out_dir}  (Claude에 분석을 맡길 때는 *_일별.csv 와 데이터_설명.md를 함께 올리세요)")


if __name__ == "__main__":
    main()
