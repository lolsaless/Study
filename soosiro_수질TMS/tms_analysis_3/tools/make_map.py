# -*- coding: utf-8 -*-
"""
측정소·TMS 사업장·유량/기상 관측소와 연결선을 지도(HTML)로 그린다 — 연결이 맞는지 눈으로 확인용

    python tools/make_map.py            → results/map/link_map.html (브라우저로 열기, 인터넷 필요: Leaflet·OpenStreetMap 타일)

표시: 수질 측정소(파랑, stations.csv lat/lon 이 있는 곳), TMS 사업장(빨강, 45번 점수가 있으면 색 농도로),
      유량관측소(초록)·기상지점(주황, 연결된 것만), 측정소 → 연결 대상 선. data/raw/gis/*.geojson 이 있으면 구역 경계도 겹쳐 그린다.
"""
import json
import sys
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
import config as C  # noqa: E402
from core import schema  # noqa: E402

HTML = """<!doctype html><html><head><meta charset="utf-8"><title>측정소 연결 지도</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#m{height:100%;margin:0}.lg{background:#fff;padding:6px 8px;font:12px sans-serif;border-radius:4px}</style></head>
<body><div id="m"></div><script>
const D = __DATA__;
const m = L.map('m').setView([36.6, 127.7], 7);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 18, attribution: '&copy; OpenStreetMap'}).addTo(m);
if (D.gis) L.geoJSON(D.gis, {style: {color: '#888', weight: 1, fill: false}}).addTo(m);
const pt = (p, c, r, t) => L.circleMarker([p.lat, p.lon], {radius: r, color: c, fillColor: c, fillOpacity: 0.8, weight: 1}).bindPopup(t).addTo(m);
D.sites.forEach(s => pt(s, s.score == null ? '#d62728' : `hsl(0, 80%, ${30 + s.score / 2}%)`, 4, `<b>${s.site}</b> (TMS)<br>${s.score == null ? '' : '관리점수 ' + s.score.toFixed(0)}`));
D.obs.forEach(o => pt(o, o.kind == 'flow' ? '#2ca02c' : '#ff7f0e', 4, `${o.kind == 'flow' ? '유량' : '기상'} ${o.name} (${o.code})`));
D.stations.forEach(s => pt(s, '#1f77b4', 7, `<b>${s.station}</b> (${s.basin})<br>${s.note || ''}`));
D.lines.forEach(l => L.polyline(l.xy, {color: l.c, weight: 1, opacity: 0.6, dashArray: l.dash}).addTo(m));
const lg = L.control({position: 'bottomleft'}); lg.onAdd = () => { const d = L.DomUtil.create('div', 'lg');
d.innerHTML = '● 파랑 수질 측정소 ● 빨강 TMS(진할수록 점수 낮음)<br>● 초록 유량 ● 주황 기상 · 선 = 연결(점선 = 추정)'; return d; }; lg.addTo(m);
const all = [...D.sites, ...D.obs, ...D.stations].map(p => [p.lat, p.lon]); if (all.length) m.fitBounds(all, {padding: [20, 20]});
if (!D.stations.length) alert('stations.csv 에 측정소 좌표(lat, lon)가 아직 없어 TMS·관측소만 표시합니다(자료요구서 A-1).');
</script></body></html>"""


def main():
    st = schema.read("stations")
    sites = pd.read_csv(C.TMS_SITE_COORDS, encoding="utf-8-sig").dropna(subset=["lat", "lon"]) if C.TMS_SITE_COORDS.exists() else pd.DataFrame(columns=["site", "lat", "lon"])
    sc = C.RESULTS_DIR / "45_facility_score" / "facility_scores.csv"
    if sc.exists():
        s = pd.read_csv(sc, encoding="utf-8-sig").groupby("site")["종합점수"].min()
        sites["score"] = sites["site"].map(s)
    obs = schema.read("obs_stations") if schema.available("obs_stations") else pd.DataFrame(columns=["kind", "code", "name", "lat", "lon"])
    used = set(st["flow_obscd"].dropna()) | set(st["weather_stn"].dropna())
    obs = obs[obs["code"].isin(used)].dropna(subset=["lat", "lon"])
    stx = st.dropna(subset=["lat", "lon"])
    lines = []
    sxy = sites.set_index("site")[["lat", "lon"]]
    oxy = obs.drop_duplicates("code").set_index("code")[["lat", "lon"]]
    for _, r in stx.iterrows():
        est = "추정" in str(r.get("link_note", ""))
        for s in str(r["upstream_tms"]).split(";") if pd.notna(r["upstream_tms"]) else []:
            if s in sxy.index:
                lines.append({"xy": [[r["lat"], r["lon"]], sxy.loc[s].tolist()], "c": "#d62728", "dash": "4" if est else None})
        for col, c in [("flow_obscd", "#2ca02c"), ("weather_stn", "#ff7f0e")]:
            if pd.notna(r[col]) and r[col] in oxy.index:
                lines.append({"xy": [[r["lat"], r["lon"]], oxy.loc[r[col]].tolist()], "c": c, "dash": "4" if est else None})
    gis = None
    gj = sorted(C.GIS_DIR.glob("*.geojson")) if C.GIS_DIR.exists() else []
    if gj:
        gis = json.loads(gj[0].read_text(encoding="utf-8"))
    data = {"stations": stx[["station", "basin", "lat", "lon"]].assign(note=stx["link_note"].fillna("")).to_dict("records"),
            "sites": sites[["site", "lat", "lon"] + (["score"] if "score" in sites else [])].astype(object).where(sites.notna(), None).to_dict("records"),
            "obs": obs[["kind", "code", "name", "lat", "lon"]].to_dict("records"), "lines": lines, "gis": gis}
    out = C.RESULTS_DIR / "map" / "link_map.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(HTML.replace("__DATA__", json.dumps(data, ensure_ascii=False, default=str)), encoding="utf-8")
    print(f"[저장] {out}  (측정소 {len(stx)}·TMS {len(sites)}·관측소 {len(obs)}·연결선 {len(lines)})")


if __name__ == "__main__":
    main()
