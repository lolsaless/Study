"""위도·경도 파일(CSV/엑셀)을 읽어 VWorld 배경지도 위에 점으로 표시하고 HTML 지도로 저장한다.

사용 예
    python latlon_map.py 좌표.csv
    python latlon_map.py 좌표.xlsx --name 사업장명 --out 결과지도.html
    python latlon_map.py 좌표.csv --lat 위도 --lon 경도
    python latlon_map.py            # 인자가 없으면 예시 좌표 3개로 지도 생성

사전 준비
    pip install folium pandas python-dotenv openpyxl
    같은 폴더(또는 상위 폴더)의 .env 파일에  VWORLD_API_KEY=발급받은키  한 줄 저장
"""
from __future__ import annotations

import argparse
import os
import unicodedata
import webbrowser
from pathlib import Path

import folium
import pandas as pd
from dotenv import find_dotenv, load_dotenv
from folium.plugins import Fullscreen, MarkerCluster, MousePosition

# 위도/경도 열 이름 후보 (소문자·공백 제거 후 비교)
LAT_CANDIDATES = ["위도", "lat", "latitude", "y", "ycoord", "y좌표"]
LON_CANDIDATES = ["경도", "lon", "lng", "long", "longitude", "x", "xcoord", "x좌표"]
NAME_CANDIDATES = ["사업소", "사업장명", "사업장", "시설명", "시설", "이름", "name", "명칭"]
ADDR_CANDIDATES = ["주소", "소재지", "address", "addr"]

# 이름에 들어 있는 글자로 시설 종류를 나누어 색을 다르게 표시 (위에서부터 먼저 맞는 것)
TYPE_RULES = [("폐수", "orange"), ("하수", "blue"), ("정수", "green")]
OTHER_COLOR = "purple"   # 위에 해당 없음(공장·발전소 등)
MISMATCH_COLOR = "red"   # 이름과 주소의 지역이 달라 확인이 필요한 점


def nfc(text: str) -> str:
    """맥(NFD)·윈도우(NFC) 한글 차이를 없애기 위해 NFC로 통일."""
    return unicodedata.normalize("NFC", str(text))


def read_table(path: Path) -> pd.DataFrame:
    """CSV(utf-8/cp949 자동 판별) 또는 엑셀 파일을 읽는다."""
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm", ".xls"):
        df = pd.read_excel(path)
    elif suffix in (".csv", ".txt"):
        df = None
        for enc in ("utf-8-sig", "cp949", "euc-kr"):
            try:
                df = pd.read_csv(path, encoding=enc)
                break
            except UnicodeDecodeError:
                continue
        if df is None:
            raise ValueError("CSV 인코딩을 읽을 수 없습니다. (utf-8, cp949 모두 실패)")
    else:
        raise ValueError(f"지원하지 않는 형식입니다: {suffix} (csv, xlsx만 가능)")
    df.columns = [nfc(c).strip() for c in df.columns]
    return df


def find_column(df: pd.DataFrame, given: str | None, candidates: list[str], label: str) -> str:
    if given:
        given = nfc(given).strip()
        if given not in df.columns:
            raise KeyError(f"{label} 열 '{given}'이(가) 없습니다. 있는 열: {list(df.columns)}")
        return given
    norm = {c: c.lower().replace(" ", "") for c in df.columns}
    for cand in candidates:
        for col, n in norm.items():
            if n == cand:
                return col
    raise KeyError(f"{label} 열을 자동으로 찾지 못했습니다. --{label[:3]} 옵션으로 열 이름을 지정하세요. 있는 열: {list(df.columns)}")


def find_optional(df: pd.DataFrame, given: str | None, candidates: list[str]) -> str | None:
    """없어도 되는 열(이름·주소). 못 찾으면 None."""
    try:
        return find_column(df, given, candidates, "선택")
    except KeyError:
        return None


def facility_color(name: str) -> str:
    for key, color in TYPE_RULES:
        if key in name:
            return color
    return OTHER_COLOR


def region_mismatch(name: str, addr: str) -> bool:
    """이름 앞 2글자(예: 연천) 또는 괄호 안 지역(예: (화성))이 주소에 없으면 True."""
    import re
    if not addr or not name or name.endswith("(주)"):
        return False   # 회사명(주)은 지역이 이름에 없으므로 검사하지 않음
    for m in re.findall(r"\(([^)]+)\)", name):
        if m != "주" and m[:2] in addr:
            return False
    return name[:2] not in addr


def clean_coordinates(df: pd.DataFrame, lat_col: str, lon_col: str) -> pd.DataFrame:
    """숫자 변환, 결측·범위 오류 제거, 위도/경도 뒤바뀜 자동 보정."""
    out = df.copy()
    out[lat_col] = pd.to_numeric(out[lat_col], errors="coerce")
    out[lon_col] = pd.to_numeric(out[lon_col], errors="coerce")
    n0 = len(out)
    out = out.dropna(subset=[lat_col, lon_col])

    # 한국 범위(위도 33~39, 경도 124~132) 기준으로 위도·경도가 서로 바뀐 행 보정
    swapped = out[lat_col].between(124, 132) & out[lon_col].between(33, 39)
    if swapped.any():
        print(f"[알림] 위도·경도가 뒤바뀐 것으로 보이는 {swapped.sum()}행을 맞바꿨습니다.")
        out.loc[swapped, [lat_col, lon_col]] = out.loc[swapped, [lon_col, lat_col]].values

    valid = out[lat_col].between(-90, 90) & out[lon_col].between(-180, 180)
    out = out[valid]
    dropped = n0 - len(out)
    if dropped:
        print(f"[알림] 좌표가 비었거나 범위를 벗어난 {dropped}행은 제외했습니다.")
    return out


def add_vworld_layers(m: folium.Map, api_key: str) -> None:
    """VWorld 타일(일반/위성/회색/야간)을 레이어로 추가한다."""
    base = f"https://api.vworld.kr/req/wmts/1.0.0/{api_key}"
    layers = [
        ("VWorld 일반", f"{base}/Base/{{z}}/{{y}}/{{x}}.png", True),
        ("VWorld 위성", f"{base}/Satellite/{{z}}/{{y}}/{{x}}.jpeg", False),
        ("VWorld 회색", f"{base}/gray/{{z}}/{{y}}/{{x}}.png", False),
        ("VWorld 야간", f"{base}/midnight/{{z}}/{{y}}/{{x}}.png", False),
    ]
    for name, url, show in layers:
        folium.TileLayer(
            tiles=url, attr="© VWorld (국토교통부)", name=name,
            overlay=False, control=True, show=show, max_zoom=19,
        ).add_to(m)


def build_map(df: pd.DataFrame, lat_col: str, lon_col: str, name_col: str | None,
              api_key: str, cluster: bool = True, addr_col: str | None = None) -> folium.Map:
    center = [df[lat_col].mean(), df[lon_col].mean()]
    m = folium.Map(location=center, zoom_start=11, tiles=None, control_scale=True)
    add_vworld_layers(m, api_key)

    parent = MarkerCluster(name="좌표 점").add_to(m) if cluster else folium.FeatureGroup(name="좌표 점").add_to(m)
    for _, row in df.iterrows():
        # 팝업에는 원본 표의 모든 열을 보여준다
        rows_html = "".join(
            f"<tr><th style='text-align:left;padding-right:8px'>{c}</th><td>{row[c]}</td></tr>"
            for c in df.columns
        )
        tooltip = str(row[name_col]) if name_col else f"{row[lat_col]:.5f}, {row[lon_col]:.5f}"
        color = facility_color(tooltip) if name_col else "blue"
        if name_col and addr_col and region_mismatch(str(row[name_col]), str(row[addr_col])):
            color = MISMATCH_COLOR
            tooltip += "  ⚠ 이름·주소 지역 불일치(확인 필요)"
        folium.Marker(
            location=[row[lat_col], row[lon_col]],
            tooltip=tooltip,
            popup=folium.Popup(f"<table>{rows_html}</table>", max_width=360),
            icon=folium.Icon(color=color, icon="info-sign"),
        ).add_to(parent)

    # 전체 점이 한 화면에 들어오도록 확대 수준 자동 조정
    m.fit_bounds([[df[lat_col].min(), df[lon_col].min()], [df[lat_col].max(), df[lon_col].max()]],
                 max_zoom=16)
    folium.LayerControl(collapsed=False).add_to(m)
    if name_col:
        legend = (
            "<div style='position:fixed;bottom:25px;left:10px;z-index:9999;background:white;"
            "padding:8px 10px;border:1px solid #999;border-radius:6px;font-size:12px'>"
            "<b>시설 구분</b><br>"
            "<span style='color:#38a9dc'>●</span> 하수 &nbsp;<span style='color:#f69730'>●</span> 폐수 "
            "&nbsp;<span style='color:#72b026'>●</span> 정수<br>"
            "<span style='color:#d63e2a'>●</span> 이름·주소 불일치(확인 필요)<br>"
            "<span style='color:#d252b9'>●</span> 기타(사업장 등)</div>"
        )
        m.get_root().html.add_child(folium.Element(legend))
    Fullscreen().add_to(m)
    MousePosition(prefix="좌표", num_digits=5).add_to(m)
    return m


def main() -> None:
    ap = argparse.ArgumentParser(description="위도·경도 파일을 VWorld 지도로 표시")
    ap.add_argument("input", nargs="?", help="CSV 또는 엑셀 파일 경로 (생략하면 예시 데이터)")
    ap.add_argument("--lat", help="위도 열 이름 (생략 시 자동 탐지)")
    ap.add_argument("--lon", help="경도 열 이름 (생략 시 자동 탐지)")
    ap.add_argument("--name", help="마우스를 올렸을 때 보일 이름 열 (생략 시 자동 탐지)")
    ap.add_argument("--addr", help="주소 열 (생략 시 자동 탐지)")
    ap.add_argument("--out", default="map.html", help="저장할 HTML 파일 (기본 map.html)")
    ap.add_argument("--no-cluster", action="store_true", help="점 묶음(클러스터) 끄기")
    ap.add_argument("--no-open", action="store_true", help="저장 후 브라우저를 열지 않음")
    args = ap.parse_args()

    # .env 읽기: 현재 폴더부터 상위로 찾아 올라감
    load_dotenv(find_dotenv(usecwd=True))
    api_key = os.getenv("VWORLD_API_KEY")
    if not api_key:
        raise SystemExit(".env 파일에 VWORLD_API_KEY=... 를 넣어주세요.")

    if args.input:
        path = Path(nfc(args.input)).expanduser()
        if not path.exists():
            # 맥에서 NFD로 저장된 파일명 대응: 원래 입력 그대로도 시도
            path = Path(args.input).expanduser()
        df = read_table(path)
    else:
        print("[알림] 입력 파일이 없어 예시 좌표(서울시청·대전시청·부산시청)로 만듭니다.")
        df = pd.DataFrame({
            "이름": ["서울시청", "대전시청", "부산시청"],
            "위도": [37.5663, 36.3504, 35.1798],
            "경도": [126.9779, 127.3845, 129.0750],
        })

    lat_col = find_column(df, args.lat, LAT_CANDIDATES, "위도")
    lon_col = find_column(df, args.lon, LON_CANDIDATES, "경도")
    name_col = find_optional(df, args.name, NAME_CANDIDATES)
    addr_col = find_optional(df, args.addr, ADDR_CANDIDATES)

    df = clean_coordinates(df, lat_col, lon_col)
    if df.empty:
        raise SystemExit("표시할 수 있는 좌표가 없습니다.")

    # 점검 결과를 화면에 출력
    dup = df[df.duplicated([lat_col, lon_col], keep=False)]
    if len(dup):
        print(f"[점검] 같은 좌표에 겹친 점 {len(dup)}개 (예: {', '.join(dup[name_col].astype(str).head(4)) if name_col else ''}) → 지도에서 한 점으로 겹쳐 보입니다.")
    if name_col and addr_col:
        bad = df[[region_mismatch(str(n), str(a)) for n, a in zip(df[name_col], df[addr_col])]]
        if len(bad):
            print(f"[점검] 이름과 주소 지역이 다른 {len(bad)}개 (빨간 점) — 이름·주소 중 어느 쪽이 틀렸는지 확인 필요:")
            for _, r in bad.iterrows():
                print(f"   - {r[name_col]} | {r[addr_col]}")

    m = build_map(df, lat_col, lon_col, name_col, api_key, cluster=not args.no_cluster, addr_col=addr_col)
    out = Path(args.out).expanduser().resolve()
    m.save(str(out))
    print(f"[완료] {len(df)}개 점 → {out}")
    if not args.no_open:
        webbrowser.open(out.as_uri())


if __name__ == "__main__":
    main()
