"""
SHP 뷰어 (창 + 버튼 버전)
- 실행:  python shp_viewer.py
- 설치:  python -m pip install geopandas pyogrio openpyxl matplotlib
- 기능:  [파일 열기] → 요약·속성표 미리보기 → [지도 보기] / [엑셀 저장] / [GeoJSON 저장]
         .shp 파일을 창으로 끌어다 놓지는 못하고, 버튼으로 선택한다.
- 맥에서 창이 안 뜨면:  brew install python-tk   (Homebrew 파이썬일 때)
"""
import math
import sys
import unicodedata
from pathlib import Path

# ── 바꿀 수 있는 값 ──────────────────────────────────────────────
ENCODINGS = ["utf-8", "cp949", "euc-kr"]   # 앞에서부터 시도
PREVIEW_ROWS = 500                          # 화면에 보여줄 최대 행 수
MAP_WARN_COUNT = 50000                      # 도형이 이만큼 넘으면 지도 그리기 전에 물어봄
MAP_FONTS = ["Malgun Gothic", "AppleGothic", "NanumGothic"]   # 지도 제목의 한글 글꼴
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
# ────────────────────────────────────────────────────────────────

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:
    sys.exit(
        "tkinter(창 기능)가 없습니다.\n"
        "  맥: brew install python-tk\n"
        "  윈도우: 파이썬 재설치 시 'tcl/tk' 항목 체크\n"
        "창 없이 쓰려면 read_shp.py 를 사용하세요."
    )

import geopandas as gpd


def read_shp(path: Path):
    """인코딩을 바꿔 가며 읽는다. 반환: (표, 사용한 인코딩)"""
    last_err = None
    for enc in ENCODINGS:
        try:
            gdf = gpd.read_file(path, encoding=enc)
            cols = [c for c in gdf.columns if c != "geometry"]
            broken = any(gdf[c].astype(str).str.contains("�").any() for c in cols)
            if broken:
                continue
            return gdf, enc
        except Exception as e:
            last_err = e
    raise RuntimeError(f"읽기 실패: {last_err}")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SHP 뷰어")
        self.geometry("980x640")
        self.gdf = None
        self.path = None

        # 메뉴
        menu = tk.Menu(self)
        m_file = tk.Menu(menu, tearoff=0)
        m_file.add_command(label="열기 (Ctrl+O)", command=self.open_file)
        m_file.add_command(label="지도 보기", command=self.show_map)
        m_file.add_command(label="엑셀로 저장", command=self.save_xlsx)
        m_file.add_command(label="GeoJSON으로 저장", command=self.save_geojson)
        m_file.add_separator()
        m_file.add_command(label="종료", command=self.destroy)
        menu.add_cascade(label="파일", menu=m_file)
        self.config(menu=menu)
        self.bind("<Control-o>", lambda e: self.open_file())

        # 상단 버튼
        bar = ttk.Frame(self, padding=6)
        bar.pack(fill="x")
        ttk.Button(bar, text="파일 열기", command=self.open_file).pack(side="left")
        self.btn_x = ttk.Button(bar, text="엑셀 저장", command=self.save_xlsx, state="disabled")
        self.btn_x.pack(side="left", padx=4)
        self.btn_g = ttk.Button(bar, text="GeoJSON 저장", command=self.save_geojson, state="disabled")
        self.btn_g.pack(side="left")
        self.btn_m = ttk.Button(bar, text="지도 보기", command=self.show_map, state="disabled")
        self.btn_m.pack(side="left", padx=4)

        # 요약
        self.info = tk.Text(self, height=8, state="disabled", bg="#f6f6f6")
        self.info.pack(fill="x", padx=6)

        # 속성표
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=6, pady=6)
        self.tree = ttk.Treeview(frm, show="headings")
        sy = ttk.Scrollbar(frm, orient="vertical", command=self.tree.yview)
        sx = ttk.Scrollbar(frm, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        frm.rowconfigure(0, weight=1)
        frm.columnconfigure(0, weight=1)

        self.status = ttk.Label(self, text="[파일 열기]를 눌러 .shp 파일을 선택하세요.", anchor="w")
        self.status.pack(fill="x", padx=6, pady=(0, 6))

    # ── 동작 ──
    def open_file(self):
        raw = filedialog.askopenfilename(
            title=".shp 파일 선택", filetypes=[("Shapefile", "*.shp"), ("모든 파일", "*.*")]
        )
        if not raw:
            return
        path = Path(unicodedata.normalize("NFC", raw))
        try:
            gdf, enc = read_shp(path)
        except Exception as e:
            messagebox.showerror("읽기 실패", str(e))
            return
        self.gdf, self.path = gdf, path
        missing = [e for e in (".shx", ".dbf") if not path.with_suffix(e).exists()]

        lines = [
            f"파일       : {path.name}",
            f"인코딩     : {enc}",
            f"행(도형) 수 : {len(gdf)}",
            f"도형 종류  : {gdf.geom_type.unique().tolist()}",
            f"좌표계     : {gdf.crs}" + ("" if gdf.crs else "  [확인 필요: .prj 파일 없음]"),
            f"범위       : {gdf.total_bounds.round(4).tolist()}",
        ]
        if missing:
            lines.append(f"[확인 필요] 같은 폴더에 {missing} 파일이 없습니다.")
        self.info.config(state="normal")
        self.info.delete("1.0", "end")
        self.info.insert("end", "\n".join(lines))
        self.info.config(state="disabled")

        df = gdf.drop(columns="geometry")
        cols = list(df.columns)
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = cols
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=110, anchor="w")
        for row in df.head(PREVIEW_ROWS).astype(str).itertuples(index=False):
            self.tree.insert("", "end", values=list(row))
        shown = min(len(df), PREVIEW_ROWS)
        self.status.config(text=f"속성표 {shown}행 표시 (전체 {len(df)}행)")
        self.btn_x.config(state="normal")
        self.btn_g.config(state="normal")
        self.btn_m.config(state="normal")

    def show_map(self):
        """새 창에 지도를 그린다. 아래 도구줄로 확대·이동·저장(PNG) 가능."""
        n = len(self.gdf)
        if n > MAP_WARN_COUNT and not messagebox.askyesno(
            "도형이 많습니다", f"도형이 {n:,}개라 그리는 데 시간이 걸릴 수 있습니다.\n계속할까요?"
        ):
            return
        try:
            import matplotlib
            matplotlib.use("TkAgg")
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
            from matplotlib.figure import Figure
        except ImportError:
            messagebox.showerror("matplotlib 필요", "python -m pip install matplotlib 을 먼저 실행하세요.")
            return
        matplotlib.rcParams["font.sans-serif"] = MAP_FONTS + matplotlib.rcParams["font.sans-serif"]
        matplotlib.rcParams["axes.unicode_minus"] = False

        top = tk.Toplevel(self)
        top.title(f"지도 - {self.path.name}")
        top.geometry("900x720")
        fig = Figure(figsize=(9, 7))
        ax = fig.add_subplot(111)
        gdf = self.gdf[~self.gdf.geometry.isna() & ~self.gdf.geometry.is_empty]
        if gdf.empty:
            top.destroy()
            messagebox.showwarning("그릴 도형 없음", "도형이 비어 있습니다. [확인 필요]")
            return
        polys = gdf.geom_type.isin(["Polygon", "MultiPolygon"]).all()
        if polys:
            gdf.plot(ax=ax, facecolor="#cfe3f7", edgecolor="#1a5fb4", linewidth=0.4)
        else:
            gdf.plot(ax=ax, color="#1a5fb4", linewidth=0.6, markersize=6)
        if self.gdf.crs and self.gdf.crs.is_geographic:
            ax.set_aspect(1 / max(0.1, abs(math.cos(math.radians(gdf.total_bounds[[1, 3]].mean())))))
        ax.set_title(unicodedata.normalize("NFC", self.path.stem))
        ax.grid(True, linewidth=0.3)
        canvas = FigureCanvasTkAgg(fig, master=top)
        NavigationToolbar2Tk(canvas, top)   # 확대·이동·저장 도구줄
        canvas.get_tk_widget().pack(fill="both", expand=True)
        canvas.draw()

    def _out(self, suffix):
        OUTPUT_DIR.mkdir(exist_ok=True)
        stem = unicodedata.normalize("NFC", self.path.stem)
        return OUTPUT_DIR / f"{stem}{suffix}"

    def save_xlsx(self):
        out = self._out("_속성표.xlsx")
        self.gdf.drop(columns="geometry").astype(str).to_excel(out, index=False)
        messagebox.showinfo("저장 완료", str(out))

    def save_geojson(self):
        out = self._out(".geojson")
        g = self.gdf.to_crs(4326) if self.gdf.crs else self.gdf
        g.to_file(out, driver="GeoJSON")
        messagebox.showinfo("저장 완료", str(out))


if __name__ == "__main__":
    App().mainloop()
