# -*- coding: utf-8 -*-
"""
수질자동측정망 시간자료(xlsx) → 권역별 '일별' 통계 데이터 (merge_water_day.py)

[하는 일]
1. 폴더를 고르면 하위 폴더까지 모든 .xlsx(시간자료)를 읽는다(여러 파일을 동시에 읽어 빠르다).
   파일명 규칙: [권역_측정소]시간자료(YYYYMMDD-YYYYMMDD).xlsx   예) [한강_가평]시간자료(20240101-20241231).xlsx
2. ND·공란은 결측으로 처리한다. ND 위주인 항목(VOC 등 측정하지 않는 항목)은 그 측정소에서 제외한다.
3. 권역(한강·금강·낙동강·영산강)별로 연도 구분 없이 합친 뒤, 측정소별 '하루' 단위로 변수마다
   평균(mean)·최소(min)·최대(max)·중앙값(med)·유효 시간수(n)를 계산한다.
   간헐적으로 ND가 나온 항목(주로 총인)은 그날의 ND 시간수(_nd)도 함께 기록한다.
4. 권역 하나가 끝날 때마다 즉시 Data 폴더에 저장한다.

[결과: 선택한 폴더 안 Data/]
  한강_일별.csv         1행 = 1측정소 × 1일. 핵심 수질 9항목만(분석용 기본 파일, 가볍다)
  한강_일별_전체.csv/.pkl  핵심 9항목 + 부가 항목(독성·중금속 등)
  한강_커버리지.csv     측정소별 자료 있는 날, 항목별 자료 비율(%), 미측정 항목
  데이터_설명.md        컬럼 설명서 (Claude에게 분석을 맡길 때 *_일별.csv와 함께 올리면 됨)
  file_log.csv, merge_report.txt   처리 기록

[컬럼 이름 규칙]  <변수코드>_<통계>   예) TN_mean, TN_min, TN_max, TN_med, TN_n, TP_nd
  mean 평균 / min 최소 / max 최대 / med 중앙값 / n 그날 값이 있는 시간 수(0~24) / nd 그날 ND 시간 수

필요 패키지: pandas, openpyxl
실행:  python merge_water_day.py                     (폴더 선택 창, 모든 권역)
       python merge_water_day.py "/폴더/경로"          (경로 지정)
       python merge_water_day.py "/폴더/경로" 한강      (한강만)  ← 권역 이름은 여러 개 가능
"""
import re
import sys
import subprocess
import unicodedata
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

# ───────────── 설정 ─────────────
ND_TOKENS = {"ND", "N.D", "N.D.", "-", "--", "불검출", "미측정", "NA", "N/A", ""}
# 한 파일 안에서 어떤 항목의 (공란 제외) 값 중 ND 비율이 이 이상이면 '측정하지 않는 항목'으로 보고 전체를 제외
ND_DROP_RATIO = 0.5
# 간헐적 ND(검출한계 미만일 가능성)의 처리: None = 결측으로 둠 / 0.5 = '검출한계×0.5'로 대체
# (검출한계는 그 파일에서 그 항목의 최솟값(양수)으로 추정). 대체해도 _nd 열은 그대로 남는다.
ND_FILL_RATIO = None
DROP_EMPTY_COLUMNS = True      # 권역 안 모든 측정소에서 값이 하나도 없는 항목 열은 삭제
DROP_EMPTY_DAYS = True         # 모든 항목이 하루 종일 비어 있는 날(행)은 일별 파일에서 뺀다(커버리지에는 반영)
OUT_DIRNAME = "Data"           # 선택한 폴더 안에 만들어질 저장 폴더 이름
SAVE_HOURLY = False            # True면 권역별 시간자료(통합)도 함께 저장 (용량 큼)
ONLY_RIVERS = None             # 예: ["한강"]  (None이면 전체). 명령줄 인자로도 지정 가능
N_WORKERS = 4                  # 파일을 동시에 읽는 개수(1이면 순차)

FILE_RE = re.compile(r"\[(?P<river>[^_\]]+)_(?P<station>[^\]]+)\].*?\((?P<s>\d{8})-(?P<e>\d{8})\)")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
ND_FLAG = "|ND"                # 시간자료 단계에서 ND 여부를 담는 임시 열 이름 꼬리표


def nfc(x) -> str:
    """macOS는 파일명을 분해형(NFD)으로 주므로, 한글을 조합형(NFC)으로 통일한다.
    (안 하면 df['하천'] == '한강' 비교가 전부 False가 된다)"""
    return unicodedata.normalize("NFC", str(x))


# ───────────── 변수 코드표 ─────────────
CORE_CODES = ["WT", "pH", "EC", "DO", "Turb", "TOC", "TN", "TP", "Chl_a"]
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
    "암모니아성질소": ("NH3_N", "암모니아성질소", "mg/L"),
    "질산성질소": ("NO3_N", "질산성질소", "mg/L"),
    "인산염인": ("PO4_P", "인산염인", "mg/L"),
    "카드뮴": ("Cd", "카드뮴", "μg/L"),
    "납": ("Pb", "납", "μg/L"),
    "구리": ("Cu", "구리", "μg/L"),
    "아연": ("Zn", "아연", "μg/L"),
    "페놀": ("Phenol", "페놀", "mg/L"),
}
STATS = ["mean", "min", "max", "median", "count"]
STAT_SUFFIX = {"mean": "mean", "min": "min", "max": "max", "median": "med", "count": "n"}


def code_of(col: str):
    """원본 열 이름 → (코드, 항목명, 단위).
    맨 끝 괄호는 '단위'(한글이 없는 경우: ℃, mg/L, NTU, % …)일 때만 떼어낸다.
    '(좌)' '(우)' '(발광박테리아)'처럼 한글이 든 괄호는 항목 이름의 일부로 남긴다."""
    col = nfc(col)
    m = re.search(r"\s*\(([^()]*)\)\s*$", col)
    if m and not re.search(r"[가-힣]", m.group(1)):
        base, unit = col[:m.start()].strip(), m.group(1).strip()
    else:
        base, unit = col.strip(), ""
    if base in VAR_MAP:
        return VAR_MAP[base]
    return (re.sub(r"\W+", "_", base).strip("_"), base, unit)


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
def river_of(p: Path) -> str:
    m = FILE_RE.search(nfc(p.name))
    return m["river"] if m else nfc(p.parent.name or "미상")


def read_one(path: Path, root: Path):
    """returns (DataFrame[하천,측정소,측정일시,항목...,항목|ND...], 로그 dict)"""
    m = FILE_RE.search(nfc(path.name))
    river = river_of(path)
    station_fn = m["station"] if m else nfc(path.stem)
    period = f"{m['s']}-{m['e']}" if m else ""

    raw = pd.read_excel(path, header=None, dtype=str, engine="openpyxl")
    # 머리글 행: 첫 칸이 '측정일'인 행. 데이터: 첫 칸이 날짜 형식인 행
    hdr = raw.index[raw.iloc[:, 0].astype(str).str.strip() == "측정일"]
    if len(hdr) == 0:
        raise ValueError("'측정일' 머리글 행을 찾지 못함")
    names = [nfc(re.sub(r"\s+", " ", str(x)).strip()) for x in raw.iloc[hdr[0]].tolist()]
    body = raw[raw.iloc[:, 0].astype(str).str.match(DATE_RE)].copy()
    body.columns = names
    n_rows = len(body)

    dt = pd.to_datetime(body["측정일"].str.strip(), errors="coerce")
    n_bad_date = int(dt.isna().sum())
    body = body[dt.notna()].copy()

    st_col = body["측정소명"].map(lambda x: nfc(x).strip() if isinstance(x, str) else "") \
        if "측정소명" in body else pd.Series("", index=body.index)
    station = st_col.where(st_col != "", station_fn)

    items = [c for c in names if c not in ("측정일", "측정소명") and c != "nan"]
    cols = {"하천": river, "측정소": station.values, "측정일시": dt[dt.notna()].values}
    log = {"파일": nfc(str(path.relative_to(root))), "하천": river, "측정소": station_fn, "파일명기간": period,
           "행수": n_rows, "날짜오류": n_bad_date,
           "실제기간": f"{dt.min():%Y%m%d}-{dt.max():%Y%m%d}" if dt.notna().any() else "",
           "ND항목": "", "미측정항목(ND위주)": "", "숫자변환실패": 0, "이상값제외": 0}
    nd_info, dropped, n_conv_fail, n_range = [], [], 0, 0
    nd_set = {t.upper() for t in ND_TOKENS if t}
    for c in items:
        s = body[c].astype(str).str.strip().where(body[c].notna(), "")
        is_nd = s.str.upper().isin(nd_set) & (s != "")
        blank = s == ""
        num = pd.to_numeric(s.str.replace(",", "", regex=False), errors="coerce")
        conv_fail = num.isna() & ~is_nd & ~blank
        n_conv_fail += int(conv_fail.sum())
        code = code_of(c)[0]
        # 물리적으로 불가능한 값(음수, pH 0~14 밖)은 결측 처리하고 개수를 기록
        bad = (num < 0) if code != "WT" else (num < -5)
        if code == "pH":
            bad = (num < 0) | (num > 14)
        n_range += int(bad.sum())
        num[bad] = np.nan

        n_nd, n_valid_or_nd = int(is_nd.sum()), int((~blank).sum())
        if n_nd:
            nd_info.append(f"{c}:{n_nd}")
        mostly_nd = n_valid_or_nd > 0 and n_nd / n_valid_or_nd >= ND_DROP_RATIO
        if mostly_nd:                             # 측정하지 않는 항목 → 이 측정소에서는 제외(NaN)
            dropped.append(c)
            num[:] = np.nan
        elif n_nd:                                # 간헐적 ND(검출한계 미만 가능성) → 표시를 남김
            cols[c + ND_FLAG] = is_nd.values.astype("int8")
            if ND_FILL_RATIO is not None and (num > 0).any():
                num[is_nd] = num[num > 0].min() * ND_FILL_RATIO   # 기본(None)은 결측 그대로
        cols[c] = num.values
    log["ND항목"] = ", ".join(nd_info)
    log["미측정항목(ND위주)"] = ", ".join(dropped)
    log["숫자변환실패"] = n_conv_fail
    log["이상값제외"] = n_range
    return pd.DataFrame(cols), log


def _safe_read(args):
    path, root = args
    try:
        return path, read_one(path, root), None
    except Exception as e:  # 한 파일이 깨져도 나머지는 계속
        return path, None, f"{e}"


# ───────────── 일별 변환 ─────────────
def to_daily(hourly: pd.DataFrame):
    """시간자료 → 측정소×일 통계표. returns (daily, var_info, variants)"""
    keys = ("하천", "측정소", "측정일시")
    items = [c for c in hourly.columns if c not in keys and not c.endswith(ND_FLAG)]
    flags = [c for c in hourly.columns if c.endswith(ND_FLAG)]

    # 같은 코드로 매칭되는 열(예: 머리글 표기만 다른 경우)은 하나로 합친다(행마다 값이 있는 쪽 사용)
    groups = {}
    for c in items:
        code, kor, unit = code_of(c)
        groups.setdefault(code, []).append((c, kor, unit))
    h = {k: hourly[k] for k in keys}
    info, variants = {}, {}
    for code, cols in groups.items():
        names = [c for c, _, _ in cols]
        h[code] = hourly[names].bfill(axis=1).iloc[:, 0] if len(names) > 1 else hourly[names[0]]
        info[code] = (cols[0][1], " / ".join(dict.fromkeys(u for _, _, u in cols if u)))
        if len(names) > 1:
            variants[code] = names
    nd_codes = []
    for f in flags:
        code = code_of(f[:-len(ND_FLAG)])[0]
        h[code + "_nd"] = (h[code + "_nd"] + hourly[f].fillna(0)) if (code + "_nd") in h else hourly[f].fillna(0)
        if code not in nd_codes:
            nd_codes.append(code)
    h = pd.DataFrame(h)
    h["날짜"] = h["측정일시"].dt.normalize()
    codes = list(info)

    g = h.groupby(["하천", "측정소", "날짜"])
    agg = g[codes].agg(STATS)
    agg = agg.reindex(columns=pd.MultiIndex.from_product([codes, STATS]))
    agg.columns = [f"{c}_{STAT_SUFFIX[s]}" for c, s in agg.columns]
    agg = agg.round({c: 4 for c in agg.columns if not c.endswith("_n")})
    if nd_codes:
        nd = g[[c + "_nd" for c in nd_codes]].sum().astype("int16")
        agg = pd.concat([agg, nd], axis=1)
    # 열 순서: 변수별로 mean,min,max,med,n,(nd)
    order = []
    for c in codes:
        order += [f"{c}_{STAT_SUFFIX[s]}" for s in STATS] + ([f"{c}_nd"] if c in nd_codes else [])
    agg = agg[order].reset_index()
    meta = pd.DataFrame({"연도": agg["날짜"].dt.year, "월": agg["날짜"].dt.month,
                         "시간기록수": g.size().values}, index=agg.index)
    daily = pd.concat([agg[["하천", "측정소"]], agg["날짜"].dt.strftime("%Y-%m-%d").rename("날짜"),
                       meta, agg[order]], axis=1)
    return daily, info, variants


def split_core(daily: pd.DataFrame):
    meta = ["하천", "측정소", "날짜", "연도", "월", "시간기록수"]
    core = meta + [c for c in daily.columns if c not in meta and c.rsplit("_", 1)[0] in CORE_CODES]
    return daily[core]


def coverage_table(daily: pd.DataFrame, codes: list):
    """측정소 × 항목: 달력 기준 '값이 있는 날'의 비율(%). 빈 날 제거 전의 표로 계산한다."""
    has = pd.concat([(daily[f"{c}_n"] > 0).rename(c) for c in codes], axis=1)
    has["측정소"] = daily["측정소"].values
    g = has.groupby("측정소")
    cov = (g[codes].mean() * 100).round(1)
    any_day = (daily[[f"{c}_n" for c in codes]] > 0).any(axis=1)
    cov.insert(0, "자료있는날", any_day.groupby(daily["측정소"].values).sum().astype(int))
    cov.insert(0, "달력일수", g.size())
    core = [c for c in CORE_CODES if c in codes]
    extra = [c for c in codes if c not in CORE_CODES]
    cov["미측정_핵심항목"] = [", ".join(c for c in core if cov.loc[s, c] == 0) or "-" for s in cov.index]
    cov["측정하는_부가항목"] = [", ".join(c for c in extra if cov.loc[s, c] > 0) or "-" for s in cov.index]
    return cov.reset_index()


def write_doc(out_dir: Path, summaries: list, var_info: dict, river_docs: dict):
    L = ["# 수질자동측정망 일별 통계 데이터 설명서", "",
         "이 폴더의 `*_일별.csv`는 수질자동측정망 **시간자료를 측정소별 하루 단위로 요약**한 것입니다.", "",
         "## 파일 구조",
         "- 권역(수계)별로 파일이 나뉘며(한강·금강·낙동강·영산강), 여러 연도가 한 파일에 들어 있습니다.",
         "- `<권역>_일별.csv`: 핵심 수질 9항목만 (분석 기본 파일)",
         "- `<권역>_일별_전체.csv`: 핵심 9항목 + 부가 항목(독성 감시, 중금속 등). 부가 항목이 있는 권역에만 생깁니다.",
         "- `<권역>_커버리지.csv`: 측정소별 자료 있는 날 수, 항목별 자료 비율, 미측정 항목",
         "- **1행 = 1측정소 × 1일** (하루 종일 값이 하나도 없는 날은 행에서 제외했습니다. 달력 기준 비율은 커버리지 파일 참조)", "",
         "## 컬럼",
         "| 컬럼 | 설명 |", "|---|---|",
         "| 하천 | 권역(수계) 이름 |", "| 측정소 | 측정소 이름 |", "| 날짜 | YYYY-MM-DD |",
         "| 연도, 월 | 날짜에서 뽑은 값 |", "| 시간기록수 | 그날 시간자료 행 수(정상이면 24) |",
         "| `<코드>_mean / _min / _max / _med` | 그날 시간값들의 평균 / 최솟값 / 최댓값 / 중앙값 |",
         "| `<코드>_n` | 그날 값이 실제로 있는 시간 수(0~24). 신뢰도 판단용 |",
         "| `<코드>_nd` | 그날 ND(불검출)로 기록된 시간 수. ND가 간헐적으로 나온 항목에만 있음(주로 TP) |", "",
         "## 변수 코드",
         "| 코드 | 항목 | 단위 | 구분 |", "|---|---|---|---|"]
    for code, (kor, unit) in var_info.items():
        L.append(f"| {code} | {kor} | {unit} | {'핵심' if code in CORE_CODES else '부가'} |")
    L += ["", "## 결측·ND 처리 규칙",
          "- **결측은 0이 아니라 빈칸(NaN)** 입니다. 하루 중 값이 하나도 없으면 `_mean/_min/_max/_med`는 빈칸, `_n`은 0입니다.",
          "- 통계는 값이 있는 시간만으로 계산합니다. **`_n`이 작은 날(예: 18시간 미만)은 하루를 대표하지 못할 수 있으니** "
          "분석 목적에 맞게 `_n` 기준으로 걸러 쓰세요.",
          "- 원자료의 `ND`는 값이 아니라 결측으로 처리했습니다.",
          "  - 어떤 측정소에서 한 항목의 ND가 50% 이상이면 측정하지 않는 항목으로 보고 그 측정소의 해당 항목은 전부 결측입니다(VOC 등).",
          "  - ND가 간헐적인 항목(주로 총인 TP)은 **검출한계 미만**일 가능성이 큽니다. ND 시간은 평균에서 빠지므로 "
          "`_mean`이 실제보다 높게 나올 수 있습니다. 그날의 ND 시간 수가 `<코드>_nd`에 있으니 필요하면 보정하세요.",
          "- 물리적으로 불가능한 값(음수, pH 0~14 밖)은 결측 처리했습니다(개수는 file_log.csv의 `이상값제외`).",
          "- 같은 측정소·같은 시각이 중복되면 첫 번째 값만 사용했습니다.",
          "- 수온·탁도·클로로필-a의 0 값은 실제 낮은 값일 수 있어 그대로 두었습니다.", "",
          "## 권역별 요약"]
    L += [f"- {s}" for s in summaries]
    for river, (cov, nd_tab) in river_docs.items():
        L += ["", f"## {river} 측정소별 자료 현황",
              "| 측정소 | 달력일수 | 자료있는날 | 미측정 핵심항목 | 측정하는 부가항목 |", "|---|---|---|---|---|"]
        for _, r in cov.iterrows():
            L.append(f"| {r['측정소']} | {r['달력일수']} | {r['자료있는날']} | {r['미측정_핵심항목']} | {r['측정하는_부가항목']} |")
        if len(nd_tab):
            L += ["", f"{river}에서 ND가 간헐적으로 나온 항목(ND 시간 / 전체 기록 시간):"]
            L += [f"- {code}: {int(a):,} / {int(b):,} ({a / b:.1%})" for code, (a, b) in nd_tab.items()]
    (out_dir / "데이터_설명.md").write_text("\n".join(L), encoding="utf-8")


# ───────────── 메인 ─────────────
def main():
    root = pick_folder()
    if not root.is_dir():
        sys.exit(f"폴더가 아닙니다: {root}")
    only = [nfc(r) for r in (sys.argv[2:] if len(sys.argv) > 2 else (ONLY_RIVERS or []))]
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
    if only:
        by_river = {r: v for r, v in by_river.items() if r in only}
        print(f"[처리 대상] {', '.join(by_river) or '없음(권역 이름 확인)'}")

    all_logs, errors, summary, var_info_all, river_docs, nd_item_counts = [], [], [], {}, {}, {}
    pool = ProcessPoolExecutor(max_workers=N_WORKERS) if N_WORKERS > 1 else None
    try:
        for river, plist in by_river.items():
            print(f"\n=== {river} ({len(plist)}개 파일) ===")
            frames = []
            jobs = [(p, root) for p in plist]
            results = pool.map(_safe_read, jobs) if pool else map(_safe_read, jobs)
            for i, (p, res, err) in enumerate(results, 1):
                if err:
                    errors.append(f"{p.name}: {err}")
                    print(f"  ({i}/{len(plist)}) {nfc(p.name)}  [실패] {err}")
                    continue
                df, lg = res
                frames.append(df)
                all_logs.append(lg)
                for t in lg["미측정항목(ND위주)"].split(", "):
                    if t:
                        nd_item_counts[t] = nd_item_counts.get(t, 0) + 1
                print(f"  ({i}/{len(plist)}) {nfc(p.name)}  {lg['행수']:,}행")
            pd.DataFrame(all_logs).to_csv(out_dir / "file_log.csv", index=False, encoding="utf-8-sig")
            if not frames:
                continue

            hourly = pd.concat(frames, ignore_index=True, sort=False)
            del frames
            key = ["측정소", "측정일시"]
            n_dup = int(hourly.duplicated(key).sum())
            hourly = hourly.drop_duplicates(key, keep="first").sort_values(key).reset_index(drop=True)
            item_cols = [c for c in hourly.columns if c not in ("하천", "측정소", "측정일시") and not c.endswith(ND_FLAG)]
            empty_cols = [c for c in item_cols if hourly[c].notna().sum() == 0]
            if DROP_EMPTY_COLUMNS and empty_cols:
                hourly = hourly.drop(columns=empty_cols + [c + ND_FLAG for c in empty_cols if c + ND_FLAG in hourly])
            n_hourly = len(hourly)
            if SAVE_HOURLY:
                hourly.to_pickle(out_dir / f"{river}_시간통합.pkl")

            daily, info, variants = to_daily(hourly)
            del hourly
            var_info_all.update(info)
            if variants:
                print("  [참고] 머리글 표기가 다른 같은 항목을 합쳤습니다: " +
                      "; ".join(f"{k}←{v}" for k, v in variants.items()))
            codes = list(info)

            cov = coverage_table(daily, codes)                     # 빈 날 제거 전 기준(달력일수)
            n_cal = len(daily)
            if DROP_EMPTY_DAYS:
                daily = daily[(daily[[f"{c}_n" for c in codes]] > 0).any(axis=1)].reset_index(drop=True)
            nd_tab = {}
            for c in codes:
                if f"{c}_nd" in daily:
                    a, b = int(daily[f"{c}_nd"].sum()), int(daily[f"{c}_nd"].sum() + daily[f"{c}_n"].sum())
                    if b:
                        nd_tab[c] = (a, b)
            river_docs[river] = (cov, nd_tab)

            # ── 즉시 저장 ──
            core = split_core(daily)
            core.to_csv(out_dir / f"{river}_일별.csv", index=False, encoding="utf-8-sig")
            if len(core.columns) < len(daily.columns):
                daily.to_csv(out_dir / f"{river}_일별_전체.csv", index=False, encoding="utf-8-sig")
            daily.to_pickle(out_dir / f"{river}_일별_전체.pkl")
            cov.to_csv(out_dir / f"{river}_커버리지.csv", index=False, encoding="utf-8-sig")
            yrs = ", ".join(f"{y}:{n:,}" for y, n in daily["연도"].value_counts().sort_index().items())
            line = (f"**{river}**: 측정소 {daily['측정소'].nunique()}개, 일별 {len(daily):,}행 "
                    f"(자료 없는 날 {n_cal - len(daily):,}행 제외, {daily['날짜'].min()}~{daily['날짜'].max()}), "
                    f"연도별 일수 [{yrs}], 원 시간자료 {n_hourly:,}행(중복 제거 {n_dup:,}행), "
                    f"삭제한 빈 항목 {len(empty_cols)}개")
            summary.append(line)
            write_doc(out_dir, summary, var_info_all, river_docs)
            print(f"  → 저장 완료: {out_dir / (river + '_일별.csv')}\n  {line}")
            del daily, core, cov
    finally:
        if pool:
            pool.shutdown()

    flog = pd.DataFrame(all_logs)
    mismatch = flog[(flog["파일명기간"] != "") & (flog["파일명기간"] != flog["실제기간"])] if len(flog) else flog
    lines = ["수질 일별 변환 보고서", f"폴더: {root}", f"읽은 파일: {len(all_logs)} / {sum(len(v) for v in by_river.values())}개", ""]
    lines += [s.replace("**", "") for s in summary]
    lines += ["", f"ND 위주(≥{ND_DROP_RATIO:.0%})라 제외한 (파일·항목) 건수: {sum(nd_item_counts.values())}건"]
    lines += [f"  - {k}: {v}개 파일" for k, v in sorted(nd_item_counts.items(), key=lambda x: -x[1])]
    lines += [f"파일명 기간과 실제 기간이 다른 파일: {len(mismatch)}개"]
    lines += ["  - " + r for r in mismatch["파일"].tolist()] if len(mismatch) else []
    if len(flog):
        lines.append(f"날짜 변환 실패 행: {int(flog['날짜오류'].sum())}, 숫자 변환 실패 값: {int(flog['숫자변환실패'].sum())}, "
                     f"이상값(음수·pH 범위 밖) 제외: {int(flog['이상값제외'].sum())}")
    if errors:
        lines += ["읽기 실패 파일:"] + ["  - " + e for e in errors]
    (out_dir / "merge_report.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n" + "\n".join(lines))
    print(f"\n[완료] 결과 폴더: {out_dir}  (Claude에 분석을 맡길 때는 *_일별.csv 와 데이터_설명.md를 함께 올리세요)")


if __name__ == "__main__":
    main()
