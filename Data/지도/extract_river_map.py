"""Extract river polygons around research sites and create a local preview map."""

import argparse
import csv
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
import os
import subprocess
import sys
import venv
from html import escape
from math import isfinite
from pathlib import Path
from tempfile import TemporaryDirectory

MAP_DIR = Path(__file__).resolve().parent
REQUIREMENTS = MAP_DIR / "requirements-map.txt"
RESEARCH_SITES = (MAP_DIR.parents[2] / "연구사업" / "analysis_hantan_river"
                  / "00_설정" / "site_basin.csv")
WGS84 = "EPSG:4326"
METRIC_CRS = "EPSG:5179"
DEFAULT_MARGIN_M = 3000
POLYGONS = ("Polygon", "MultiPolygon")
SITE_FIELDS = ("site", "type", "midbasin_auto", "receiving_station", "in_scope")


def requirements_met():
    lines = REQUIREMENTS.read_text(encoding="utf-8").splitlines()
    try:
        from packaging.requirements import Requirement
    except ImportError:
        return False

    for line in lines:
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        requirement = Requirement(line)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            if not requirement.specifier.contains(version(requirement.name)):
                return False
        except PackageNotFoundError:
            return False
    return True


def launch_in_map_environment():
    environment = MAP_DIR / ".venv-map"
    interpreter = (environment / "Scripts" / "python.exe" if os.name == "nt"
                   else environment / "bin" / "python")
    if not interpreter.is_file():
        print(f"지도용 가상환경을 만듭니다. {environment}", flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)

    script = str(Path(__file__).resolve())
    probe = ("from runpy import run_path; import sys; "
             "sys.exit(not run_path(sys.argv[1])['requirements_met']())")
    if subprocess.run([str(interpreter), "-c", probe, script]).returncode:
        print(f"{REQUIREMENTS.name}의 지도 패키지를 설치합니다.", flush=True)
        subprocess.run([str(interpreter), "-m", "pip", "install", "-r", str(REQUIREMENTS)],
                       check=True)
    return subprocess.call([str(interpreter), script, *sys.argv[1:]])


def choose_shapefile():
    if sys.platform == "darwin":
        result = subprocess.run(
            ["osascript", "-e",
             'POSIX path of (choose file with prompt "실폭하천 Shapefile (.shp)을 선택하세요")'],
            capture_output=True, text=True,
        )
        if result.returncode:
            if "(-128)" in result.stderr:
                return None
            raise ValueError(result.stderr.strip() or "SHP 파일 선택창을 열 수 없습니다.")
        return Path(result.stdout.rstrip("\n"))

    from tkinter import Tk, filedialog

    window = Tk()
    try:
        window.withdraw()
        selected = filedialog.askopenfilename(
            parent=window, title="실폭하천 Shapefile 선택", filetypes=[("Shapefile", "*.shp")]
        )
    finally:
        window.destroy()
    return Path(selected) if selected else None


def read_sites(path, all_sites):
    import geopandas as gpd

    rows = []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"site", "lat", "lon"} | (set() if all_sites else {"in_scope"})
        if missing := required.difference(reader.fieldnames or []):
            raise ValueError(f"CSV 필수 열 누락: {', '.join(sorted(missing))}")
        for row in reader:
            if not all_sites and (row.get("in_scope") or "").strip() != "1":
                continue
            try:
                lat, lon = float(row["lat"]), float(row["lon"])
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    raise ValueError
            except (ValueError, TypeError) as exc:
                raise ValueError(f"CSV {reader.line_num}행 좌표 오류: {row['site']}") from exc
            if not (row["site"] or "").strip():
                raise ValueError(f"CSV {reader.line_num}행 지점명 누락")
            rows.append({key: row.get(key) or "" for key in SITE_FIELDS} | {"lat": lat, "lon": lon})
    if not rows:
        raise ValueError("선택된 지점이 없습니다.")
    return gpd.GeoDataFrame(
        rows, geometry=gpd.points_from_xy([row["lon"] for row in rows],
                                         [row["lat"] for row in rows]),
        crs=WGS84,
    )


def polygon_parts(frame):
    frame = frame.explode(ignore_index=True)
    # make_valid 결과에 포함될 수 있는 선·점은 면 레이어에서 제외한다.
    if (frame.geom_type == "GeometryCollection").any():
        frame = frame.explode(ignore_index=True)
    return frame.loc[frame.geom_type.isin(POLYGONS) & ~frame.geometry.is_empty].copy()


def make_area(sites, basin, margin_m):
    import geopandas as gpd
    from shapely.geometry import box

    if basin is None:
        west, south, east, north = sites.to_crs(METRIC_CRS).total_bounds
        area = box(west - margin_m, south - margin_m, east + margin_m, north + margin_m)
        return gpd.GeoSeries([area], crs=METRIC_CRS)

    boundary = gpd.read_file(basin, engine="pyogrio")
    if boundary.empty or boundary.crs is None or not boundary.geom_type.isin(POLYGONS).all():
        raise ValueError("유역 경계에는 좌표계가 정의된 폴리곤이 필요합니다.")
    boundary = boundary.to_crs(METRIC_CRS)
    boundary.geometry = boundary.geometry.make_valid()
    area = polygon_parts(boundary).geometry.union_all()
    if area.is_empty:
        raise ValueError("유역 경계에 유효한 면이 없습니다.")
    outside = sites.loc[~sites.to_crs(METRIC_CRS).geometry.covered_by(area), "site"]
    if not outside.empty:
        raise ValueError(f"유역 경계 밖의 선택 지점: {', '.join(outside)}")
    return gpd.GeoSeries([area], crs=METRIC_CRS)


def extract_rivers(source, area):
    import geopandas as gpd
    import pyogrio

    if source.suffix.lower() != ".shp":
        raise ValueError("수계 입력은 Shapefile(.shp)이어야 합니다.")
    for suffix in (".shp", ".shx", ".dbf", ".prj"):
        part = source if suffix == ".shp" else source.with_suffix(suffix)
        if not part.is_file():
            raise FileNotFoundError(part)
    info = pyogrio.read_info(source)
    if not info["crs"]:
        raise ValueError("하천 Shapefile의 좌표계를 확인할 수 없습니다.")
    mask = area.to_crs(info["crs"]).iloc[0]
    # 전국 레이어에서 후보만 읽고, 실제 도형은 선택 영역 경계로 자른다.
    fields = [field for field in info["fields"] if field.upper() in {"UFID", "SCLS", "FMTA"}]
    rivers = pyogrio.read_dataframe(source, bbox=mask.bounds, columns=fields)
    rivers.geometry = rivers.geometry.make_valid()
    rivers = gpd.clip(polygon_parts(rivers), mask)
    rivers = polygon_parts(rivers)
    if rivers.empty:
        raise ValueError("선택 영역과 겹치는 실폭하천 면이 없습니다.")
    return rivers.to_crs(WGS84)


def render_map(rivers, sites, area, area_label, path):
    import folium

    river_map = folium.Map(tiles=None, control_scale=True)
    boundary = area.to_crs(WGS84)
    folium.GeoJson(
        boundary, name=area_label,
        style_function=lambda _: {"color": "#666666", "weight": 1.5,
                                  "dashArray": "5 4", "fill": False},
        zoom_on_click=False,
    ).add_to(river_map)
    folium.GeoJson(
        rivers[["geometry"]], name="실폭하천",
        style_function=lambda _: {"color": "#17668a", "weight": 1, "fillOpacity": 0.55},
    ).add_to(river_map)
    markers = folium.FeatureGroup(name="연구 지점").add_to(river_map)
    for row in sites.itertuples(index=False):
        details = "<br>".join(escape(value) for value in
                              (row.site, row.type, row.midbasin_auto, row.receiving_station)
                              if value)
        folium.CircleMarker(
            [row.lat, row.lon], radius=5, color="#8e3519", fill=True,
            fill_color="#dc643b", fill_opacity=0.95, tooltip=escape(row.site),
            popup=folium.Popup(details, max_width=260),
        ).add_to(markers)
    west, south, east, north = boundary.total_bounds
    river_map.fit_bounds([[south, west], [north, east]])
    folium.LayerControl().add_to(river_map)
    river_map.save(str(path))


def ask_margin_m():
    while True:
        answer = input(f"지도 여유 폭(km) [{DEFAULT_MARGIN_M / 1000:g}]: ").strip()
        if not answer:
            return DEFAULT_MARGIN_M
        try:
            margin_m = float(answer) * 1000
        except ValueError:
            margin_m = 0
        if isfinite(margin_m) and margin_m > 0:
            return margin_m
        print("0보다 큰 숫자를 입력하세요. 예: 10")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--river-shp", type=Path, help="실폭하천 .shp. 생략하면 선택창 표시")
    local_sites = MAP_DIR / "site_basin.csv"
    parser.add_argument("--sites", type=Path,
                        default=local_sites if local_sites.is_file() else RESEARCH_SITES)
    parser.add_argument("--out", type=Path, help="새 결과 폴더. 생략하면 output/river_map_날짜_시각")
    parser.add_argument("--all-sites", action="store_true", help="in_scope 조건 없이 표시")
    area_options = parser.add_mutually_exclusive_group()
    area_options.add_argument("--margin-m", type=float, default=DEFAULT_MARGIN_M, help="미리보기 여유 폭(m)")
    area_options.add_argument("--basin", type=Path, help="확정된 유역 경계 파일(단일 레이어)")
    args = parser.parse_args()
    if not isfinite(args.margin_m) or args.margin_m <= 0:
        parser.error("--margin-m은 유한한 양수여야 합니다.")
    if args.out is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        args.out = MAP_DIR / "output" / f"river_map_{timestamp}"
    if args.out.exists():
        parser.error(f"새 결과 폴더를 지정하세요: {args.out}")

    try:
        if not requirements_met():
            if Path(sys.prefix).resolve() == MAP_DIR / ".venv-map":
                raise ValueError(f"{REQUIREMENTS.name}의 패키지가 설치 요건을 충족하지 않습니다.")
            return launch_in_map_environment()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"지도 실행 환경 준비 실패: {exc}\n")

    import geopandas as gpd
    import pyogrio

    if len(sys.argv) == 1 and sys.stdin.isatty():
        try:
            args.margin_m = ask_margin_m()
        except (EOFError, KeyboardInterrupt):
            print("\n실행을 취소했습니다.")
            return 0

    try:
        source = args.river_shp or choose_shapefile()
        if source is None:
            print("SHP 파일 선택을 취소했습니다.")
            return 0
        sites = read_sites(args.sites, args.all_sites)
        area = make_area(sites, args.basin, args.margin_m)
        rivers = extract_rivers(source, area)
        area_label = "입력 유역 경계" if args.basin else "지점 좌표 기반 미리보기 범위"
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=args.out.parent) as temp:
            draft = Path(temp) / "map"
            draft.mkdir()
            rivers.to_file(draft / "rivers.geojson", engine="pyogrio", driver="GeoJSON", index=False)
            sites.to_file(draft / "sites.geojson", engine="pyogrio", driver="GeoJSON", index=False)
            gpd.GeoDataFrame({"area_type": [area_label]}, geometry=area.to_crs(WGS84)).to_file(
                draft / "area.geojson", engine="pyogrio", driver="GeoJSON", index=False
            )
            render_map(rivers, sites, area, area_label, draft / "map.html")
            if args.out.exists():
                raise FileExistsError(args.out)
            draft.rename(args.out)
    except (OSError, ValueError, pyogrio.errors.DataSourceError,
            pyogrio.errors.DataLayerError) as exc:
        parser.exit(1, f"추출 실패: {exc}\n")
    print(f"{area_label} | 지점 {len(sites)}개 | 하천 면 {len(rivers)}개 | {args.out.resolve()}")


if __name__ == "__main__":
    sys.exit(main())
