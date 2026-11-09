# -*- coding: utf-8 -*-
"""
TMS 사업장 소재지(data/tms_location.csv) → 위도·경도(WGS84) 변환  (geocode_tms_location.py)

[두 단계]
1) 오프라인(기본, API 키 불필요)
   주소에서 시군·구·읍면·동·리 이름을 뽑아 법정 행정구역 경계(VWorld 법정동·법정리 경계)와 맞춘 뒤, 그 구역의 중심점을 좌표로 쓴다.
   → 정확도는 '리/동 중심' 수준(대개 0.5~3 km 오차). 기상 지점 매칭(21번)·하천 측정소 연결에는 충분하다.
2) 정밀화(선택, 사용자 PC에서 API 키로 실행)
   VWorld 지오코더(지번→도로명 순)로 번지 단위 좌표를 받아 덮어쓴다. 실패한 곳만 1)의 값이 남는다.
     python geocode_tms_location.py --vworld-key 발급받은키
   (VWorld 키: https://www.vworld.kr → 인증키 발급, 무료. 카카오 키는 --kakao-key)

[결과: data/]
  tms_location_geocoded.csv  사업소, 소재지, sigun, lat, lon, precision, matched, admin_code, x_5186, y_5186, note
  site_coords.csv            site, lat, lon, sigun, address  ← 21_merge_weather.py 가 읽는 양식

  precision: 주소(API) > 리 > 동 > 읍면 > 시군구.  '읍면'·'시군구'는 꼭 지도로 확인하거나 API로 정밀화할 것.
  x_5186, y_5186: GRS80 중부원점 TM(EPSG:5186, m) — 국내 GIS(QGIS·ArcGIS)에서 거리 계산용

필요 패키지: pandas, shapely, pyproj(선택: TM 좌표)
  pip install pandas shapely pyproj
경계 자료: krgc 저장소(github.com/WSN1010/krgc, MIT)의 법정 읍면동·리 경계(VWorld, 2026-08 수집)를
          처음 실행할 때 data/_boundary_cache/ 로 내려받는다(약 100MB, git 에는 올리지 않음).
실행: python geocode_tms_location.py                 (오프라인)
      python geocode_tms_location.py --vworld-key KEY  (정밀화)
      python geocode_tms_location.py --krgc-data /경로/data   (경계 자료를 이미 받아 둔 폴더)
"""
from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import os
import re
import struct
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd
from shapely import from_wkb
from shapely.ops import unary_union

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
IN_CSV = DATA_DIR / "tms_location.csv"
OUT_CSV = DATA_DIR / "tms_location_geocoded.csv"
OUT_COORDS = DATA_DIR / "site_coords.csv"

GG = "41"  # 경기도 법정동 코드 앞 2자리

# 경계 자료(2023 기준)의 시군구 이름 → 현재 시군 이름
SGG_TO_SIGUN = {"덕양구": "고양시", "일산동구": "고양시", "일산서구": "고양시",
                "처인구": "용인시", "기흥구": "용인시", "수지구": "용인시", "여주군": "여주시"}
# 주소에 쓰인 옛 이름 → 경계 자료 이름
SIGUN_ALIAS = {"여주군": "여주시"}
EMD_ALIAS = {"중부면": "남한산성면", "능서면": "세종대왕면", "가남면": "가남읍",
             "이동면": "이동읍", "남사면": "남사읍", "여주읍": None, "교하읍": None, "오포읍": None}

# 도로명만 있어 행정구역 이름이 없거나 부족한 주소에 대한 보조 힌트(근거가 약하면 note 에 표시)
MANUAL_HINTS = {
    "평택현곡폐수": ("현곡리", "현곡산업단지(청북읍 현곡리) 기준"),
    "여주능서하수": ("세종대왕면", "옛 능서면(마장로) 기준"),
    "남양주가운하수": ("다산동", "가운로(옛 가운동, 현 다산동) 기준 추정"),
    "남양주별내하수": ("별내동", "화접리 일대(현 별내동) 기준 추정"),
    "시흥목감하수": ("목감동", "시설명 기준 추정"),
    "화성남양하수": ("마도면", "마도공단로 기준 추정"),
    "화성동탄2하수": ("동탄구", "동탄산단 기준 — 구 단위"),
}


# ───────────── 경계 자료 읽기 ─────────────
KRGC_RAW = "https://raw.githubusercontent.com/WSN1010/krgc/main/krgc/data/"   # MIT 라이선스, VWorld 경계(2026-08 수집)
CACHE_DIR = DATA_DIR / "_boundary_cache"


def find_krgc_data(cli_path: str | None) -> Path:
    """경계 자료 폴더. 지정이 없으면 krgc 저장소(GitHub)에서 emd·ri 를 한 번 내려받아 data/_boundary_cache 에 둔다."""
    if cli_path:
        return Path(cli_path)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for lv in ("emd", "ri"):
        for suf in ("wkb.gz", "meta.json.gz"):
            f = CACHE_DIR / f"{lv}.{suf}"
            if not f.exists():
                print(f"경계 자료 내려받는 중: {f.name} (처음 한 번, 약 100MB)")
                urllib.request.urlretrieve(KRGC_RAW + f.name, f)
    return CACHE_DIR


def load_level(data_dir: Path, level: str):
    blob = gzip.decompress((data_dir / f"{level}.wkb.gz").read_bytes())
    metas = json.loads(gzip.decompress((data_dir / f"{level}.meta.json.gz").read_bytes()))
    geoms, off = [], 0
    while off < len(blob):
        (n,) = struct.unpack_from("<I", blob, off)
        off += 4
        geoms.append(from_wkb(blob[off:off + n]))
        off += n
    rows = []
    for g, m in zip(geoms, metas):
        if not str(m.get("code", "")).startswith(GG):
            continue
        sgg = m.get("sigungu") or ""
        sigun = SGG_TO_SIGUN.get(sgg) or re.sub(r"^(\S+?[시군])\s?(\S+구)$", r"\1", sgg)
        rows.append({**m, "sigun": sigun, "geom": g})
    return pd.DataFrame(rows)


def rep_point(g):
    c = g.centroid
    return c if g.contains(c) else g.representative_point()


# ───────────── 주소 해석 ─────────────
def norm_addr(a: str) -> str:
    a = re.sub(r"\s+", " ", str(a)).strip()
    a = re.sub(r"^경기\s", "경기도 ", a)
    return a


def parse_addr(addr: str) -> dict:
    a = norm_addr(addr)
    toks = re.split(r"[\s(),]+", a)
    out = {"sigun": None, "gu": None, "emd": [], "dong": [], "ri": []}
    for t in toks:
        if out["sigun"] is None and re.fullmatch(r"[가-힣]+[시군]", t) and t not in ("경기도",):
            out["sigun"] = SIGUN_ALIAS.get(t, t)
            continue
        if re.fullmatch(r"[가-힣]+구", t):
            out["gu"] = t
        if re.fullmatch(r"[가-힣]+[읍면]", t):
            out["emd"].append(t)
        m = re.match(r"^([가-힣]+?\d*[가-힣]*리)(?:\d|산|$)", t)
        if m and not t.endswith(("로", "길")):
            out["ri"].append(m.group(1))
        m = re.match(r"^([가-힣]+\d*[가-힣]*동)(?:\d|산|$)", t)
        if m and not t.endswith(("로", "길")) and not t.endswith("구"):
            out["dong"].append(m.group(1))
    return out


def name_variants(n: str) -> list[str]:
    """신평2리→신평리, 매탄3동→매탄동, 와동리→와동동(리가 동으로 바뀐 곳)"""
    v = [n, re.sub(r"\d+", "", n)]
    base = re.sub(r"\d+", "", n)
    if base.endswith("리"):
        v.append(base[:-1] + "동")
    if base.endswith("동"):
        v.append(base[:-1] + "리")
    return list(dict.fromkeys(v))


class Matcher:
    def __init__(self, data_dir: Path):
        self.emd = load_level(data_dir, "emd")
        if (data_dir / "sigungu.wkb.gz").exists():
            self.sgg = load_level(data_dir, "sigungu")
        else:  # 시군구 경계가 없으면 읍면동을 합쳐 만든다
            self.sgg = (self.emd.groupby(["sigungu", "sigun"])
                        .agg(geom=("geom", lambda g: unary_union(list(g))), code=("code", "first"))
                        .reset_index())
        self.ri = load_level(data_dir, "ri")

    def _hit(self, df, col, names, sigun, emd_hint=None):
        sub = df[(df["sigun"] == sigun) & (df[col].isin(names))]
        if len(sub) > 1 and emd_hint:
            s2 = sub[sub["emd"].isin(emd_hint)]
            if len(s2):
                sub = s2
        return sub

    def match(self, site: str, addr: str) -> dict:
        p = parse_addr(addr)
        sigun = p["sigun"]
        note = []
        if site in MANUAL_HINTS:
            h, why = MANUAL_HINTS[site]
            if h.endswith("구"):
                p["gu"] = h
            else:
                (p["ri"] if h.endswith("리") else p["dong"] if h.endswith("동") else p["emd"]).insert(0, h)
            note.append("보조힌트: " + why)
        if sigun is None:
            return {"precision": "실패", "note": "시군을 찾지 못함"}
        emd_hint = [EMD_ALIAS.get(e, e) for e in p["emd"]]
        emd_hint = [e for e in emd_hint if e]

        # 1) 리
        for r in p["ri"]:
            sub = self._hit(self.ri, "ri", name_variants(r), sigun, emd_hint)
            if len(sub) == 1:
                return self._out(sub.iloc[0], "리", f"{sub.iloc[0]['emd']} {sub.iloc[0]['ri']}", note)
            sub2 = self._hit(self.emd, "emd", name_variants(r), sigun)  # 리가 동으로 바뀐 곳
            if len(sub2) == 1:
                return self._out(sub2.iloc[0], "동", sub2.iloc[0]["emd"], note + [f"{r}→{sub2.iloc[0]['emd']}"])
            if len(sub) > 1:
                note.append(f"{r} 동명 {len(sub)}곳")
        # 2) 동
        for d in p["dong"]:
            sub = self._hit(self.emd, "emd", name_variants(d), sigun)
            if p["gu"] and len(sub) > 1:
                s2 = sub[sub["sigungu"].str.endswith(p["gu"])]
                sub = s2 if len(s2) else sub
            if len(sub) == 1:
                return self._out(sub.iloc[0], "동", sub.iloc[0]["emd"], note)
        # 3) 읍면
        for e in emd_hint:
            sub = self.emd[(self.emd["sigun"] == sigun) & (self.emd["emd"] == e)]
            if len(sub) == 1:
                return self._out(sub.iloc[0], "읍면", e, note + ["읍면 중심 — 확인 필요"])
        # 4) 시군구(구가 있으면 구)
        sub = self.sgg[self.sgg["sigun"] == sigun]
        if p["gu"]:
            s2 = sub[sub["sigungu"].str.endswith(p["gu"])]
            sub = s2 if len(s2) else sub
        if len(sub):
            u = unary_union(list(sub["geom"]))
            pt = rep_point(u)
            return {"lat": round(pt.y, 6), "lon": round(pt.x, 6), "precision": "시군구",
                    "matched": " ".join(sub["sigungu"].tolist()), "admin_code": sub.iloc[0]["code"][:5],
                    "note": "; ".join(note + ["시군구 중심 — 반드시 확인"])}
        return {"precision": "실패", "note": "; ".join(note + ["행정구역 일치 없음"])}

    @staticmethod
    def _out(row, prec, matched, note):
        pt = rep_point(row["geom"])
        return {"lat": round(pt.y, 6), "lon": round(pt.x, 6), "precision": prec,
                "matched": f"{row['sigungu']} {matched}", "admin_code": row["code"], "note": "; ".join(note)}


# ───────────── API 정밀화(선택) ─────────────
def vworld(addr: str, key: str):
    for typ in ("PARCEL", "ROAD"):
        q = {"service": "address", "request": "getcoord", "version": "2.0", "crs": "epsg:4326",
             "address": addr, "format": "json", "type": typ, "refine": "true", "simple": "false", "key": key}
        url = "https://api.vworld.kr/req/address?" + urllib.parse.urlencode(q)
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                js = json.loads(r.read().decode("utf-8"))
            res = js.get("response", {})
            if res.get("status") == "OK":
                pt = res["result"]["point"]
                return float(pt["y"]), float(pt["x"]), "VWorld-" + typ
        except Exception as e:  # noqa: BLE001
            print("  VWorld 오류:", e)
        time.sleep(0.1)
    return None


def kakao(addr: str, key: str):
    url = "https://dapi.kakao.com/v2/local/search/address.json?" + urllib.parse.urlencode({"query": addr})
    req = urllib.request.Request(url, headers={"Authorization": f"KakaoAK {key}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            docs = json.loads(r.read().decode("utf-8")).get("documents", [])
        if docs:
            return float(docs[0]["y"]), float(docs[0]["x"]), "Kakao"
    except Exception as e:  # noqa: BLE001
        print("  Kakao 오류:", e)
    return None


def api_candidates(addr: str) -> list[str]:
    """'지번(도로명)' 형태를 지번 주소·도로명 주소 두 개로 나눈다."""
    a = norm_addr(addr)
    head = re.sub(r"\(.*?\)", "", a).strip()
    inner = re.findall(r"\(([^)]*)\)", a)
    prefix = " ".join(head.split()[:3])
    c = [head]
    for x in inner:
        x = x.strip()
        if re.search(r"\d", x) and len(x) > 3:
            c.append(f"{prefix} {x}" if not x.startswith("경기") else x)
    return list(dict.fromkeys(c))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--krgc-data", default=None)
    ap.add_argument("--vworld-key", default=os.environ.get("VWORLD_KEY"))
    ap.add_argument("--kakao-key", default=os.environ.get("KAKAO_REST_KEY"))
    args = ap.parse_args()

    loc = pd.read_csv(IN_CSV, encoding="utf-8-sig")
    loc.columns = [c.strip() for c in loc.columns]
    loc["사업소"] = loc["사업소"].astype(str).str.strip()
    m = Matcher(find_krgc_data(args.krgc_data))

    rows = []
    for _, r in loc.iterrows():
        res = m.match(r["사업소"], r["소재지"])
        rec = {"사업소": r["사업소"], "소재지": norm_addr(r["소재지"]), "sigun": parse_addr(r["소재지"])["sigun"], **res}
        if args.vworld_key or args.kakao_key:
            for cand in api_candidates(r["소재지"]):
                hit = (vworld(cand, args.vworld_key) if args.vworld_key else None) or \
                      (kakao(cand, args.kakao_key) if args.kakao_key else None)
                if hit:
                    rec.update(lat=round(hit[0], 6), lon=round(hit[1], 6), precision="주소(API)",
                               note=f"{hit[2]}: {cand}")
                    break
        rows.append(rec)
    out = pd.DataFrame(rows)

    try:
        from pyproj import Transformer
        t = Transformer.from_crs("EPSG:4326", "EPSG:5186", always_xy=True)
        ok = out["lat"].notna()
        x, y = t.transform(out.loc[ok, "lon"].values, out.loc[ok, "lat"].values)
        out.loc[ok, "x_5186"], out.loc[ok, "y_5186"] = x.round(1), y.round(1)
    except ImportError:
        print("pyproj 가 없어 TM 좌표(x_5186, y_5186)는 건너뜁니다.")

    cols = ["사업소", "소재지", "sigun", "lat", "lon", "precision", "matched", "admin_code", "x_5186", "y_5186", "note"]
    out = out.reindex(columns=cols)
    out.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    out.rename(columns={"사업소": "site", "소재지": "address"})[["site", "lat", "lon", "sigun", "address"]] \
       .to_csv(OUT_COORDS, index=False, encoding="utf-8-sig")

    print(f"저장: {OUT_CSV.name}, {OUT_COORDS.name}  ({len(out)}곳)")
    print(out["precision"].value_counts().to_string())
    chk = out[out["precision"].isin(["읍면", "시군구", "실패"])]
    if len(chk):
        print("\n확인이 필요한 곳(읍면·시군구 중심):")
        print(chk[["사업소", "소재지", "precision", "matched"]].to_string(index=False))


if __name__ == "__main__":
    main()
