"""
수계(유역) 추출 도구 — 유역 경계 안에 있는 자료만 골라낸다
- 실행:  python basin_extract.py
- 설치:  python -m pip install geopandas pyogrio openpyxl
- 준비물
    ① 유역도 파일(.shp/.geojson): '한강' 같은 수계 경계 면(Polygon)이 들어 있는 파일
    ② 추출할 자료(여러 개 가능): .shp / .geojson  또는  위도·경도 열이 있는 .xlsx / .csv
- 순서:  ① 유역도 열기 → 열·값 선택(예: 대권역명 = 한강) → ② 자료 열기 → [추출 실행]
- 결과:  output/ 폴더에  원본이름_수계추출.geojson  +  _속성표.xlsx  (행 수 요약 포함)
- 원본 파일은 수정하지 않는다.
"""
import sys
import unicodedata
from pathlib import Path

import geopandas as gpd
import pandas as pd

# ── 바꿀 수 있는 값 ──────────────────────────────────────────────
ENCODINGS = ["utf-8", "cp949", "euc-kr"]            # 속성 글자 깨짐 방지용, 앞에서부터 시도
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
LON_NAMES = ["경도", "lon", "lng", "longitude", "x", "X좌표", "경도(도)"]   # 표 자료의 경도 열 후보
LAT_NAMES = ["위도", "lat", "latitude", "y", "Y좌표", "위도(도)"]           # 표 자료의 위도 열 후보
TABLE_CRS = "EPSG:4326"                             # 표 자료 좌표계 (경도·위도 = WGS84)
MODES = {
    "걸치는 것까지 포함": "intersects",
    "완전히 안에 있는 것만": "within",
    "경계선에서 잘라내기 (면 자료용)": "clip",
}
# ────────────────────────────────────────────────────────────────


def nfc(s):
    return unicodedata.normalize("NFC", str(s))


# ───────────────────────── 핵심 기능 (창 없이도 쓸 수 있음) ─────────────────────────
def read_vector(path):
    """shp/geojson을 읽는다. 인코딩을 바꿔 가며 글자 깨짐을 피한다. 반환: (표, 인코딩)"""
    path = Path(path)
    last = None
    for enc in ENCODINGS:
        try:
            gdf = gpd.read_file(path, encoding=enc)
            cols = [c for c in gdf.columns if c != "geometry"]
            if any(gdf[c].astype(str).str.contains("�").any() for c in cols):
                continue
            return gdf, enc
        except Exception as e:
            last = e
    raise RuntimeError(f"읽기 실패: {last}")


def read_points_table(path, xcol=None, ycol=None, crs=TABLE_CRS):
    """엑셀/CSV의 위도·경도 열로 점 자료를 만든다. 열을 못 찾으면 ValueError(후보 열 목록 포함)."""
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xlsm", ".xls"):
        df = pd.read_excel(path, dtype=object)
    else:
        df = None
        for enc in ENCODINGS + ["utf-8-sig"]:
            try:
                df = pd.read_csv(path, dtype=object, encoding=enc)
                break
            except Exception:
                continue
        if df is None:
            raise RuntimeError("CSV를 읽지 못했습니다.")
    df.columns = [nfc(c).strip() for c in df.columns]
    low = {c.lower(): c for c in df.columns}
    xcol = xcol or next((low[n.lower()] for n in LON_NAMES if n.lower() in low), None)
    ycol = ycol or next((low[n.lower()] for n in LAT_NAMES if n.lower() in low), None)
    if not xcol or not ycol:
        raise ValueError(f"경도/위도 열을 찾지 못했습니다. [확인 필요] 열 목록: {list(df.columns)}")
    x = pd.to_numeric(df[xcol], errors="coerce")
    y = pd.to_numeric(df[ycol], errors="coerce")
    bad = x.isna() | y.isna()
    gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(x, y), crs=crs)
    gdf.loc[bad, "geometry"] = None          # 좌표를 못 읽은 행은 도형 없음으로 둔다 (임의로 고치지 않음)
    return gdf, int(bad.sum())


def basin_geometry(basin, col, values):
    """유역도에서 col 열 값이 values 중 하나인 면들을 하나로 합친다. 반환: (도형, 선택된 면 수)"""
    sel = basin[basin[col].astype(str).map(nfc).isin([nfc(v) for v in values])]
    if sel.empty:
        raise ValueError("선택한 값에 해당하는 유역이 없습니다.")
    return sel.geometry.union_all() if hasattr(sel.geometry, "union_all") else sel.geometry.unary_union, len(sel)


def extract(target, basin_crs, basin_geom, mode="intersects"):
    """target 자료에서 유역 안의 것만 남긴다. 좌표계가 다르면 유역도 기준으로 맞춘다.
    반환: (결과 표, 좌표계 없음 여부)"""
    no_crs = target.crs is None
    if no_crs:
        raise ValueError("자료에 좌표계(.prj)가 없습니다. [확인 필요] 좌표계를 알아야 정확히 맞출 수 있습니다.")
    t = target.to_crs(basin_crs) if target.crs != basin_crs else target
    t = t[~t.geometry.isna() & ~t.geometry.is_empty]
    if mode == "clip":
        out = gpd.clip(t, basin_geom)
    else:
        # 색인 질의는 '유역 ○○ 자료' 방향이라, "자료가 유역 안(within)"은 "유역이 자료를 포함(contains)"로 뒤집는다
        pred = "contains" if mode == "within" else mode
        idx = t.sindex.query(basin_geom, predicate=pred)     # 공간 색인으로 빠르게 찾기
        out = t.iloc[sorted(idx)]
    return out.reset_index(drop=True), no_crs


def save(result, src_name, tag="수계추출"):
    """output/ 에 GeoJSON + 속성표 엑셀로 저장한다. 반환: 저장 경로 목록"""
    OUTPUT_DIR.mkdir(exist_ok=True)
    stem = nfc(Path(src_name).stem)
    gj = OUTPUT_DIR / f"{stem}_{tag}.geojson"
    xl = OUTPUT_DIR / f"{stem}_{tag}_속성표.xlsx"
    (result.to_crs(4326) if result.crs else result).to_file(gj, driver="GeoJSON")
    result.drop(columns="geometry").astype(str).to_excel(xl, index=False)
    return [gj, xl]


# ───────────────────────────────── 창(GUI) ─────────────────────────────────
def main():
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError:
        sys.exit("tkinter(창 기능)가 없습니다.  맥: brew install python-tk  /  윈도우: 파이썬 재설치 시 tcl/tk 체크")

    root = tk.Tk()
    root.title("수계 추출 도구")
    root.geometry("760x640")
    st = {"basin": None, "targets": []}

    def log(msg):
        box.config(state="normal"); box.insert("end", msg + "\n"); box.see("end"); box.config(state="disabled")
        root.update_idletasks()

    # 1) 유역도
    f1 = ttk.LabelFrame(root, text="① 유역도 (한강 등 수계 경계)", padding=6)
    f1.pack(fill="x", padx=8, pady=6)
    lbl1 = ttk.Label(f1, text="(선택 안 됨)")
    lbl1.grid(row=0, column=1, sticky="w", padx=6)
    ttk.Label(f1, text="구분 열:").grid(row=1, column=0, sticky="e")
    cb = ttk.Combobox(f1, state="readonly", width=30)
    cb.grid(row=1, column=1, sticky="w", padx=6, pady=3)
    ttk.Label(f1, text="수계 값:\n(여러 개 선택 가능)").grid(row=2, column=0, sticky="ne")
    lb = tk.Listbox(f1, selectmode="extended", height=7, exportselection=False)
    lb.grid(row=2, column=1, sticky="we", padx=6)
    f1.columnconfigure(1, weight=1)

    def fill_values(_=None):
        lb.delete(0, "end")
        if st["basin"] is None or not cb.get():
            return
        vals = sorted({nfc(v) for v in st["basin"][cb.get()].dropna().astype(str)})
        for v in vals[:2000]:
            lb.insert("end", v)
        if len(vals) > 2000:
            log("[확인 필요] 값이 2000개를 넘어 앞 2000개만 표시합니다. 다른 열을 고르세요.")

    cb.bind("<<ComboboxSelected>>", fill_values)

    def open_basin():
        raw = filedialog.askopenfilename(title="유역도 선택", filetypes=[("지도 파일", "*.shp *.geojson *.json")])
        if not raw:
            return
        try:
            gdf, enc = read_vector(nfc(raw))
        except Exception as e:
            messagebox.showerror("읽기 실패", str(e)); return
        st["basin"] = gdf
        lbl1.config(text=f"{Path(raw).name}  (면 {len(gdf)}개, 좌표계 {gdf.crs}, 인코딩 {enc})")
        cols = [c for c in gdf.columns if c != "geometry"]
        cb.config(values=cols)
        # 이름처럼 보이는 열을 먼저 골라 준다 (최종 선택은 사용자가)
        pref = next((c for c in cols if any(k in c for k in ("권역", "수계", "유역", "NAME", "name", "명"))), cols[0] if cols else "")
        cb.set(pref); fill_values()
        log(f"유역도 열기: {Path(raw).name} — '구분 열'과 '수계 값'을 고르세요.")
        if gdf.crs is None:
            log("[확인 필요] 유역도에 좌표계가 없습니다. 결과가 어긋날 수 있습니다.")

    ttk.Button(f1, text="유역도 열기", command=open_basin).grid(row=0, column=0)

    # 2) 추출 대상
    f2 = ttk.LabelFrame(root, text="② 추출할 자료 (여러 개 가능)", padding=6)
    f2.pack(fill="x", padx=8, pady=6)
    lst = tk.Listbox(f2, height=4)
    lst.grid(row=0, column=1, sticky="we", padx=6)
    f2.columnconfigure(1, weight=1)

    def add_targets():
        raws = filedialog.askopenfilenames(
            title="추출할 자료 선택",
            filetypes=[("지도·표 파일", "*.shp *.geojson *.json *.xlsx *.xls *.csv")])
        for r in raws:
            st["targets"].append(nfc(r)); lst.insert("end", Path(r).name)

    def clear_targets():
        st["targets"].clear(); lst.delete(0, "end")

    ttk.Button(f2, text="자료 추가", command=add_targets).grid(row=0, column=0, sticky="n")
    ttk.Button(f2, text="목록 비우기", command=clear_targets).grid(row=1, column=0, sticky="n", pady=3)
    ttk.Label(f2, text="엑셀/CSV는 '위도·경도' 열이 있어야 합니다 (좌표계 WGS84 가정).").grid(row=1, column=1, sticky="w", padx=6)

    # 3) 방식
    f3 = ttk.LabelFrame(root, text="③ 추출 방식", padding=6)
    f3.pack(fill="x", padx=8, pady=6)
    mode_var = tk.StringVar(value=list(MODES)[0])
    for k in MODES:
        ttk.Radiobutton(f3, text=k, value=k, variable=mode_var).pack(anchor="w")

    # 실행
    def run():
        if st["basin"] is None or not cb.get() or not lb.curselection():
            messagebox.showinfo("확인", "유역도를 열고 '수계 값'을 선택하세요."); return
        if not st["targets"]:
            messagebox.showinfo("확인", "추출할 자료를 추가하세요."); return
        values = [lb.get(i) for i in lb.curselection()]
        try:
            geom, n = basin_geometry(st["basin"], cb.get(), values)
        except Exception as e:
            messagebox.showerror("유역 선택 오류", str(e)); return
        log(f"\n선택한 수계: {values} (면 {n}개)")
        mode = MODES[mode_var.get()]
        for tp in st["targets"]:                       # 한 파일 실패가 전체를 멈추지 않게
            name = Path(tp).name
            try:
                if Path(tp).suffix.lower() in (".xlsx", ".xls", ".csv"):
                    tgt, nbad = read_points_table(tp)
                    if nbad:
                        log(f"  [확인 필요] {name}: 좌표를 읽지 못한 행 {nbad}개 (추출에서 제외)")
                    use_mode = "intersects" if mode == "clip" else mode   # 점 자료는 자르기 불가
                else:
                    tgt, _ = read_vector(tp)
                    use_mode = mode
                res, _ = extract(tgt, st["basin"].crs, geom, use_mode)
                outs = save(res, tp)
                log(f"  ✔ {name}: 전체 {len(tgt):,}개 → 수계 안 {len(res):,}개  ({use_mode})")
                for o in outs:
                    log(f"      저장: {o}")
            except Exception as e:
                log(f"  ✘ {name}: {e}")
        messagebox.showinfo("완료", "추출이 끝났습니다. 아래 기록을 확인하세요.")

    ttk.Button(root, text="추출 실행", command=run).pack(pady=4)
    box = tk.Text(root, height=10, state="disabled", bg="#f6f6f6")
    box.pack(fill="both", expand=True, padx=8, pady=(0, 8))
    log("① 유역도 열기 → 구분 열·수계 값 선택 → ② 자료 추가 → ③ 방식 선택 → [추출 실행]")
    root.mainloop()


if __name__ == "__main__":
    main()
