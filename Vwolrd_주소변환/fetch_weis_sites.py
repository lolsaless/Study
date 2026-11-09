"""
수질측정망 하천수 지점 수집기 (VWorld 2D 데이터 API 2.0)

- 대상 레이어 : 수질측정망 하천수 지점 (서비스 ID: weissitema → data=LT_P_WEISSITEMA)
- 결과       : 실행한 폴더 아래 location_data/ 에 CSV(UTF-8-SIG)·XLSX 저장
- API 키     : 같은 폴더(또는 상위 폴더)의 .env 파일에서 VWORLD_API_KEY 를 읽음

.env 예시
    VWORLD_API_KEY=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    # (선택) 키 발급 시 등록한 서비스 URL. 오류(INCORRECT_KEY 등)가 나면 넣어 보세요.
    # VWORLD_DOMAIN=http://localhost
    # (선택) 레이어 ID가 다르면 바꿔서 사용
    # VWORLD_DATA_ID=LT_P_WEISSITEMA

필요 패키지
    pip install requests pandas openpyxl python-dotenv

실행
    python fetch_weis_sites.py
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

# ------------------------------------------------------------------
# 설정
# ------------------------------------------------------------------
API_URL = "https://api.vworld.kr/req/data"
DEFAULT_DATA_ID = "LT_P_WEISSITEMA"   # 수질측정망 하천수 지점

# 전국 범위(경도 124~132, 위도 33~39.5)를 격자로 나눠 요청
# VWorld 는 geomFilter(또는 attrFilter)가 필수이고, 한 번에 너무 넓은 범위를
# 요청하면 오류가 나는 레이어가 있어 격자 단위로 나눠 받습니다.
KOREA_BBOX = (124.0, 33.0, 132.0, 39.5)  # (minx, miny, maxx, maxy)
TILE_DEG = 1.0        # 격자 크기(도). 오류가 나면 0.5 로 줄여 보세요.
PAGE_SIZE = 1000      # VWorld 최대 1000
SLEEP_SEC = 0.2       # 요청 간 대기(서버 부하 방지)
TIMEOUT = 30
MAX_RETRY = 3

OUT_DIR = Path.cwd() / "location_data"   # 코드를 실행한 폴더 기준
OUT_STEM = "수질측정망_하천수지점"


# ------------------------------------------------------------------
# .env 읽기 (python-dotenv 가 없으면 간단 파서로 대체)
# ------------------------------------------------------------------
def load_env() -> None:
    try:
        from dotenv import load_dotenv, find_dotenv

        path = find_dotenv(usecwd=True)
        if path:
            load_dotenv(path)
            return
    except ImportError:
        pass

    for folder in [Path.cwd(), *Path.cwd().parents, Path(__file__).resolve().parent]:
        env_file = folder / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


# ------------------------------------------------------------------
# API 요청
# ------------------------------------------------------------------
def request_page(session: requests.Session, params: dict) -> dict:
    """한 페이지 요청. 일시 오류는 재시도."""
    last_err = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            r = session.get(API_URL, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last_err = e
            time.sleep(1.5 * attempt)
    raise RuntimeError(f"요청 실패({MAX_RETRY}회): {last_err}")


def fetch_box(session: requests.Session, base: dict, box: tuple) -> list[dict]:
    """격자 하나(BOX)의 모든 페이지를 받아 feature 리스트로 반환."""
    minx, miny, maxx, maxy = box
    features: list[dict] = []
    page = 1
    while True:
        params = {
            **base,
            "geomFilter": f"BOX({minx},{miny},{maxx},{maxy})",
            "size": PAGE_SIZE,
            "page": page,
        }
        js = request_page(session, params)
        resp = js.get("response", {})
        status = resp.get("status")

        if status == "NOT_FOUND":          # 해당 격자에 지점 없음
            break
        if status != "OK":
            err = resp.get("error", {})
            raise RuntimeError(
                f"API 오류 status={status}, code={err.get('code')}, "
                f"text={err.get('text')} (box={box})"
            )

        fc = resp.get("result", {}).get("featureCollection", {})
        features.extend(fc.get("features", []))

        total_pages = int(resp.get("page", {}).get("total", 1) or 1)
        if page >= total_pages:
            break
        page += 1
        time.sleep(SLEEP_SEC)
    return features


def make_tiles(bbox: tuple, step: float) -> list[tuple]:
    minx, miny, maxx, maxy = bbox
    tiles = []
    x = minx
    while x < maxx:
        y = miny
        while y < maxy:
            tiles.append((round(x, 6), round(y, 6),
                          round(min(x + step, maxx), 6), round(min(y + step, maxy), 6)))
            y += step
        x += step
    return tiles


# ------------------------------------------------------------------
# feature → 표
# ------------------------------------------------------------------
def features_to_df(features: list[dict]) -> pd.DataFrame:
    rows = []
    for f in features:
        props = dict(f.get("properties") or {})
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates")
        lon = lat = None
        if geom.get("type") == "Point" and coords:
            lon, lat = coords[0], coords[1]
        elif geom.get("type") == "MultiPoint" and coords:
            lon, lat = coords[0][0], coords[0][1]
        props["lon"] = lon
        props["lat"] = lat
        props["_feature_id"] = f.get("id")
        rows.append(props)

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # 격자 경계에 걸친 지점은 두 번 받힐 수 있으므로 중복 제거
    if df["_feature_id"].notna().all():
        df = df.drop_duplicates(subset="_feature_id")
    else:
        df = df.drop_duplicates(subset=[c for c in df.columns if c != "_feature_id"])
    df = df.drop(columns="_feature_id")

    # 좌표 열을 맨 뒤로
    cols = [c for c in df.columns if c not in ("lon", "lat")] + ["lon", "lat"]
    return df[cols].reset_index(drop=True)


# ------------------------------------------------------------------
# 메인
# ------------------------------------------------------------------
def main() -> int:
    load_env()
    key = os.getenv("VWORLD_API_KEY", "").strip()
    if not key:
        print("[오류] .env 에 VWORLD_API_KEY 가 없습니다.")
        return 1

    data_id = os.getenv("VWORLD_DATA_ID", DEFAULT_DATA_ID).strip()
    base = {
        "service": "data",
        "version": "2.0",
        "request": "GetFeature",
        "data": data_id,
        "key": key,
        "format": "json",
        "crs": "EPSG:4326",
        "geometry": "true",
        "attribute": "true",
    }
    domain = os.getenv("VWORLD_DOMAIN", "").strip()
    if domain:
        base["domain"] = domain

    tiles = make_tiles(KOREA_BBOX, TILE_DEG)
    print(f"레이어 {data_id} 수집 시작 — 격자 {len(tiles)}개")

    all_features: list[dict] = []
    failed: list[tuple] = []
    with requests.Session() as s:
        for i, box in enumerate(tiles, 1):
            try:
                feats = fetch_box(s, base, box)
                all_features.extend(feats)
                if feats:
                    print(f"  [{i:>3}/{len(tiles)}] {box} → {len(feats)}건")
            except RuntimeError as e:
                print(f"  [{i:>3}/{len(tiles)}] 실패: {e}")
                failed.append(box)
                # 키·레이어 ID 문제면 계속해도 소용없으므로 바로 중단
                msg = str(e)
                if any(t in msg for t in ("INCORRECT_KEY", "UNAVAILABLE_KEY",
                                          "INVALID_KEY", "INVALID_TYPE")):
                    print("  → API 키/도메인/레이어 ID를 확인하세요. 수집을 중단합니다.")
                    return 1
            time.sleep(SLEEP_SEC)

    df = features_to_df(all_features)
    if df.empty:
        print("[알림] 받은 지점이 없습니다. 레이어 ID(VWORLD_DATA_ID)와 키를 확인하세요.")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")
    csv_path = OUT_DIR / f"{OUT_STEM}_{stamp}.csv"
    xlsx_path = OUT_DIR / f"{OUT_STEM}_{stamp}.xlsx"

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")  # 엑셀에서 한글 깨짐 방지
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="지점목록", index=False)
        info = pd.DataFrame({
            "항목": ["레이어 ID", "수집일시", "지점 수", "좌표계", "실패 격자"],
            "값": [data_id, datetime.now().strftime("%Y-%m-%d %H:%M"), len(df),
                   "EPSG:4326 (lon=경도, lat=위도)",
                   "; ".join(map(str, failed)) if failed else "없음"],
        })
        info.to_excel(w, sheet_name="수집정보", index=False)

    print(f"\n완료: {len(df)}개 지점")
    print(f"  CSV : {csv_path}")
    print(f"  XLSX: {xlsx_path}")
    if failed:
        print(f"[주의] 실패한 격자 {len(failed)}개 — TILE_DEG 를 줄여 다시 실행해 보세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
