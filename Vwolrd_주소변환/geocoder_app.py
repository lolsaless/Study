#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
주소 → 위도·경도 변환기 (브이월드 지오코더 API) + 지도 표시

사용법
  1) 이 파일과 같은 폴더에 .env 파일을 만들고 인증키를 적는다.
         VWORLD_API_KEY=발급받은_인증키
     (처음 실행하면 .env 템플릿과 .gitignore 항목이 자동으로 만들어진다)
  2) python geocoder_app.py
  3) 브라우저가 자동으로 열린다. (http://127.0.0.1:8000)

보안
  - 인증키는 .env 에만 있고, 브라우저(HTML)로는 전달되지 않는다.
    브라우저는 이 프로그램(로컬 서버)에 요청하고, 서버가 브이월드를 대신 호출한다.
  - .env 는 .gitignore 에 자동 등록되므로 깃허브에 올라가지 않는다.
  - 서버는 127.0.0.1(내 컴퓨터)에서만 접속 가능하다.

필요 패키지: 없음 (파이썬 표준 라이브러리만 사용)
"""
import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode
from urllib.request import Request, urlopen

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
GITIGNORE_PATH = BASE_DIR / ".gitignore"

# ------------------------------------------------------------------ 설정/보안 준비


def ensure_gitignore():
    """.env 등이 깃에 올라가지 않도록 .gitignore 에 항목을 보장한다."""
    wanted = [
        ".env",
        "__pycache__/",
        "# 주소 원본/결과 파일에 개인·사업장 정보가 있을 수 있어 제외 (필요 없으면 삭제)",
        "*.xlsx",
        "*.xls",
        "*.csv",
    ]
    try:
        current = GITIGNORE_PATH.read_text(encoding="utf-8") if GITIGNORE_PATH.exists() else ""
        have = {ln.strip() for ln in current.splitlines()}
        missing = [w for w in wanted if w not in have]
        if missing:
            with open(GITIGNORE_PATH, "a", encoding="utf-8") as f:
                if current and not current.endswith("\n"):
                    f.write("\n")
                f.write("\n".join(missing) + "\n")
    except OSError as e:
        print(f"[경고] .gitignore 를 갱신하지 못했습니다: {e}")


def ensure_env_template():
    if not ENV_PATH.exists():
        ENV_PATH.write_text(
            "# 브이월드 인증키 (이 파일은 절대 깃허브에 올리지 마세요)\n"
            "VWORLD_API_KEY=\n"
            "# 인증키 발급 시 입력한 서비스 URL 도메인이 필요하면 아래 주석 해제\n"
            "# VWORLD_DOMAIN=localhost\n"
            "# PORT=8000\n",
            encoding="utf-8",
        )
        print(f"[안내] {ENV_PATH.name} 템플릿을 만들었습니다. VWORLD_API_KEY= 뒤에 인증키를 붙여넣고 다시 실행하세요.")


def load_env(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


ensure_gitignore()
ensure_env_template()
load_env(ENV_PATH)

API_KEY = os.environ.get("VWORLD_API_KEY", "").strip()
DOMAIN = os.environ.get("VWORLD_DOMAIN", "").strip()
PORT = int(os.environ.get("PORT", "8000") or 8000)


def scrub(text: str) -> str:
    """오류 메시지에 인증키가 섞여 나가지 않도록 가린다."""
    return text.replace(API_KEY, "***") if API_KEY else text


# ------------------------------------------------------------------ 브이월드 호출

_cache = {}
_cache_lock = threading.Lock()


def vworld_geocode(address: str, addr_type: str) -> dict:
    ck = (address, addr_type)
    with _cache_lock:
        if ck in _cache:
            return _cache[ck]

    params = {
        "service": "address",
        "request": "getcoord",
        "version": "2.0",
        "crs": "epsg:4326",
        "address": address,
        "refine": "true",
        "simple": "false",
        "format": "json",
        "type": addr_type,
        "key": API_KEY,
    }
    if DOMAIN:
        params["domain"] = DOMAIN
    url = "https://api.vworld.kr/req/address?" + urlencode(params)

    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:  # 네트워크/JSON 오류
        return {"ok": False, "apiError": True, "error": scrub(f"{type(e).__name__}: {e}")}

    resp = data.get("response", {})
    status = resp.get("status")
    if status == "OK":
        pt = resp["result"]["point"]
        out = {
            "ok": True,
            "lat": float(pt["y"]),
            "lon": float(pt["x"]),
            "type": addr_type,
            "refined": (resp.get("refined") or {}).get("text", ""),
        }
    elif status == "NOT_FOUND":
        out = {"ok": False, "error": "검색 결과 없음"}
    else:
        err = resp.get("error") or {}
        msg = f'{err.get("code", "")} {err.get("text", "")}'.strip() or "API 오류"
        return {"ok": False, "apiError": True, "error": scrub(msg)}

    with _cache_lock:
        _cache[ck] = out
    return out


def geocode(address: str, mode: str) -> dict:
    if not API_KEY:
        return {"ok": False, "apiError": True, "error": ".env 에 VWORLD_API_KEY 가 설정되지 않았습니다."}
    if mode in ("road", "parcel"):
        return vworld_geocode(address, mode)
    r = vworld_geocode(address, "road")  # auto: 도로명 → 지번 순서로 시도
    if not r["ok"] and not r.get("apiError"):
        r2 = vworld_geocode(address, "parcel")
        if r2["ok"] or r2.get("apiError"):
            return r2
    return r


TILE_EXT = {"Base": "png", "Satellite": "jpeg", "Hybrid": "png"}


def fetch_tile(layer: str, z: str, y: str, x: str):
    url = f"https://api.vworld.kr/req/wmts/1.0.0/{API_KEY}/{layer}/{z}/{y}/{x}.{TILE_EXT[layer]}"
    if DOMAIN:
        url += "?" + urlencode({"domain": DOMAIN})
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=15) as r:
        return r.read(), r.headers.get("Content-Type", "image/png")


# ------------------------------------------------------------------ HTTP 서버


class Handler(BaseHTTPRequestHandler):
    server_version = "GeoApp/1.0"

    def log_message(self, fmt, *args):  # 주소가 로그에 남지 않도록 조용히
        pass

    def _send(self, code, body, ctype, extra=None):
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionError):
            pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8", {"Cache-Control": "no-store"})

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)

        if u.path in ("/", "/index.html"):
            self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8", {"Cache-Control": "no-store"})

        elif u.path == "/api/status":
            self._json({"keyLoaded": bool(API_KEY)})

        elif u.path == "/api/geocode":
            address = (q.get("address", [""])[0] or "").strip()
            mode = q.get("type", ["auto"])[0]
            if not address:
                self._json({"ok": False, "error": "주소 없음"})
            else:
                self._json(geocode(address, mode if mode in ("auto", "road", "parcel") else "auto"))

        elif u.path.startswith("/tile/"):
            parts = u.path.split("/")  # ['', 'tile', layer, z, y, x]
            if (len(parts) == 6 and parts[2] in TILE_EXT and all(p.isdigit() for p in parts[3:]) and API_KEY):
                try:
                    body, ctype = fetch_tile(parts[2], parts[3], parts[4], parts[5])
                    self._send(200, body, ctype, {"Cache-Control": "public, max-age=86400"})
                except Exception:
                    self._send(404, b"", "text/plain")
            else:
                self._send(404, b"", "text/plain")

        else:
            self._send(404, b"not found", "text/plain")


# ------------------------------------------------------------------ 화면(HTML)

HTML = r'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>주소 → 위도·경도 변환기</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; font-family: "Malgun Gothic", "Apple SD Gothic Neo", sans-serif; font-size: 13px; color: #222; }
  #app { display: grid; grid-template-columns: 520px 1fr; height: 100%; }
  aside { display: flex; flex-direction: column; padding: 12px; gap: 10px; border-right: 1px solid #d0d5dd; overflow: hidden; background: #f8f9fb; }
  main, #map { height: 100%; width: 100%; }
  h1 { font-size: 16px; margin: 0; }
  section { background: #fff; border: 1px solid #e1e4ea; border-radius: 8px; padding: 10px; }
  section h2 { font-size: 13px; margin: 0 0 8px; }
  .row { display: flex; gap: 8px; align-items: center; margin-top: 6px; flex-wrap: wrap; }
  textarea { width: 100%; height: 90px; resize: vertical; font-family: inherit; font-size: 12px; padding: 6px; border: 1px solid #c9ced8; border-radius: 6px; }
  select, input[type=file] { font-size: 12px; max-width: 100%; }
  button { padding: 6px 12px; border: 1px solid #3b6fd4; background: #3b6fd4; color: #fff; border-radius: 6px; cursor: pointer; font-size: 12px; }
  button.sub { background: #fff; color: #3b6fd4; }
  button:disabled { opacity: .45; cursor: default; }
  progress { flex: 1; height: 14px; min-width: 120px; }
  .warn { background: #fff4e5; border: 1px solid #ffb74d; color: #7a4a00; padding: 8px 10px; border-radius: 6px; }
  #result { flex: 1; min-height: 0; display: flex; flex-direction: column; }
  #tbl { flex: 1; min-height: 0; overflow: auto; border: 1px solid #e1e4ea; margin-top: 6px; }
  table { border-collapse: collapse; width: max-content; min-width: 100%; font-size: 12px; }
  th, td { border-bottom: 1px solid #eceef3; padding: 4px 8px; text-align: left; white-space: nowrap; max-width: 260px; overflow: hidden; text-overflow: ellipsis; }
  th { position: sticky; top: 0; background: #eef2fb; z-index: 1; }
  tbody tr { cursor: pointer; }
  tbody tr:hover { background: #f2f6ff; }
  tr.ok .st { color: #1b7f3b; }
  tr.fail .st { color: #c62828; }
  .muted { color: #667085; }
  @media (max-width: 900px) { #app { grid-template-columns: 1fr; grid-template-rows: 55% 45%; } aside { border-right: 0; } }
</style>
</head>
<body>
<div id="app">
  <aside>
    <h1>주소 → 위도·경도 변환기 <span class="muted">(브이월드)</span></h1>
    <div id="warn" class="warn" hidden></div>

    <section>
      <h2>1. 주소 입력</h2>
      <div><input type="file" id="file" accept=".xlsx,.xls,.csv"> <span class="muted">엑셀(.xlsx/.xls) 또는 CSV</span></div>
      <div class="row muted">또는 엑셀에서 복사해서 아래에 붙여넣기 (주소 열만 복사해도 되고, 여러 열도 가능)</div>
      <textarea id="paste" placeholder="서울특별시 중구 세종대로 110&#10;경기도 수원시 팔달구 효원로 1"></textarea>
      <div class="row">
        <label><input type="checkbox" id="hasHeader" checked> 첫 행은 머리글</label>
        <label>주소 열 <select id="col"></select></label>
        <label>주소 유형
          <select id="atype">
            <option value="auto">자동 (도로명 → 지번)</option>
            <option value="road">도로명주소</option>
            <option value="parcel">지번주소</option>
          </select>
        </label>
      </div>
      <div class="row">
        <button id="run" disabled>변환 시작</button>
        <button id="stop" class="sub" disabled>중지</button>
        <progress id="prog" value="0" max="1"></progress>
        <span id="progText" class="muted"></span>
      </div>
    </section>

    <section id="result">
      <h2>2. 결과 <span id="summary" class="muted"></span></h2>
      <div class="row" style="margin-top:0">
        <button id="dlx" class="sub" disabled>엑셀로 저장</button>
        <button id="dlc" class="sub" disabled>CSV로 저장</button>
        <span class="muted">행을 클릭하면 지도에서 해당 위치로 이동합니다</span>
      </div>
      <div id="tbl"></div>
    </section>
  </aside>
  <main><div id="map"></div></main>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"></script>
<script>
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

let raw = [], headers = [], rows = [], results = [], markers = [];
let stopFlag = false, running = false;

/* ---------- 지도 ---------- */
const map = L.map('map', { preferCanvas: true }).setView([36.5, 127.8], 7);
const vBase = L.tileLayer('/tile/Base/{z}/{y}/{x}', { maxZoom: 19, attribution: '© VWorld' }).addTo(map);
const vSat  = L.tileLayer('/tile/Satellite/{z}/{y}/{x}', { maxZoom: 19, attribution: '© VWorld' });
const vHyb  = L.tileLayer('/tile/Hybrid/{z}/{y}/{x}', { maxZoom: 19 });
const osm   = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap' });
L.control.layers({ 'VWorld 일반': vBase, 'VWorld 위성': vSat, 'OpenStreetMap': osm }, { '지명 표시(위성 위)': vHyb }).addTo(map);
const group = L.featureGroup().addTo(map);

let tileOk = 0, tileErr = 0;
vBase.on('tileload', () => tileOk++);
vBase.on('tileerror', () => {
  tileErr++;
  if (tileOk === 0 && tileErr >= 6 && map.hasLayer(vBase)) {
    map.removeLayer(vBase); osm.addTo(map);
    showWarn('브이월드 배경지도를 불러오지 못해 OpenStreetMap으로 전환했습니다. (인증키의 배경지도 API 선택 여부·서비스 URL 확인)');
  }
});

function showWarn(msg) { const w = $('warn'); w.textContent = msg; w.hidden = false; }

fetch('/api/status').then(r => r.json()).then(s => {
  if (!s.keyLoaded) showWarn('.env 파일에 VWORLD_API_KEY 가 설정되어 있지 않습니다. 인증키를 넣고 프로그램을 다시 실행하세요.');
}).catch(() => {});

/* ---------- 입력 처리 ---------- */
$('file').addEventListener('change', async e => {
  const f = e.target.files[0]; if (!f) return;
  try {
    const buf = await f.arrayBuffer();
    let wb;
    if (/\.csv$/i.test(f.name)) {
      let text;
      try { text = new TextDecoder('utf-8', { fatal: true }).decode(buf); }
      catch (_) { text = new TextDecoder('euc-kr').decode(buf); }   // CP949 CSV 대응
      wb = XLSX.read(text, { type: 'string' });
    } else {
      wb = XLSX.read(buf, { type: 'array' });
    }
    const ws = wb.Sheets[wb.SheetNames[0]];
    raw = XLSX.utils.sheet_to_json(ws, { header: 1, defval: '', raw: false })
              .filter(r => r.some(c => String(c).trim() !== ''));
    $('paste').value = '';
    $('hasHeader').checked = true;
    afterLoad();
  } catch (err) { showWarn('파일을 읽지 못했습니다: ' + err.message); }
});

$('paste').addEventListener('input', () => {
  $('file').value = '';
  raw = $('paste').value.split(/\r?\n/).filter(l => l.trim() !== '').map(l => l.split('\t'));
  $('hasHeader').checked = false;   // 붙여넣기는 기본적으로 머리글 없음으로 간주
  afterLoad();
});

$('hasHeader').addEventListener('change', afterLoad);

function afterLoad() {
  buildTable(); resetResults(); renderTable();
  $('run').disabled = rows.length === 0;
  $('summary').textContent = rows.length ? `(${rows.length}건 대기)` : '';
}

function buildTable() {
  if (!raw.length) { headers = []; rows = []; $('col').innerHTML = ''; return; }
  const n = raw.reduce((m, r) => Math.max(m, r.length), 0);
  const norm = raw.map(r => Array.from({ length: n }, (_, i) => String(r[i] ?? '').trim()));
  const hh = $('hasHeader').checked;
  headers = hh ? norm[0].map((h, i) => h || ('열 ' + (i + 1))) : norm[0].map((_, i) => '열 ' + (i + 1));
  rows = hh ? norm.slice(1) : norm;
  $('col').innerHTML = headers.map((h, i) => `<option value="${i}">${esc(h)}</option>`).join('');
  let idx = headers.findIndex(h => /주소|소재지|address/i.test(h));
  $('col').value = idx < 0 ? 0 : idx;
}

function resetResults() {
  results = rows.map(() => null);
  markers = [];
  group.clearLayers();
  $('prog').value = 0; $('progText').textContent = '';
  $('dlx').disabled = true; $('dlc').disabled = true;
}

function renderTable() {
  if (!rows.length) { $('tbl').innerHTML = ''; return; }
  let h = '<table><thead><tr><th>#</th>' + headers.map(x => `<th>${esc(x)}</th>`).join('') + '<th>위도</th><th>경도</th><th>상태</th></tr></thead><tbody>';
  rows.forEach((r, i) => {
    h += `<tr id="r${i}" data-i="${i}"><td>${i + 1}</td>` + r.map(c => `<td title="${esc(c)}">${esc(c)}</td>`).join('') + '<td class="lat"></td><td class="lon"></td><td class="st"></td></tr>';
  });
  $('tbl').innerHTML = h + '</tbody></table>';
}

$('tbl').addEventListener('click', e => {
  const tr = e.target.closest('tr[data-i]'); if (!tr) return;
  const m = markers[+tr.dataset.i];
  if (m) { map.setView(m.getLatLng(), Math.max(map.getZoom(), 16)); m.openPopup(); }
});

/* ---------- 변환 ---------- */
async function fetchGeo(addr, type) {
  try {
    const res = await fetch('/api/geocode?' + new URLSearchParams({ address: addr, type }));
    return await res.json();
  } catch (e) { return { ok: false, apiError: true, error: '로컬 서버에 연결할 수 없습니다.' }; }
}

function updateRow(i) {
  const r = results[i], tr = $('r' + i); if (!tr) return;
  tr.querySelector('.lat').textContent = r.ok ? r.lat.toFixed(6) : '';
  tr.querySelector('.lon').textContent = r.ok ? r.lon.toFixed(6) : '';
  tr.querySelector('.st').textContent = r.ok ? '성공' : (r.error || '실패');
  tr.className = r.ok ? 'ok' : 'fail';
}

function addMarker(i) {
  const r = results[i], addr = rows[i][+$('col').value];
  const m = L.circleMarker([r.lat, r.lon], { radius: 7, color: '#fff', weight: 2, fillColor: '#d6336c', fillOpacity: 0.9 });
  m.bindPopup(`<b>#${i + 1}</b><br>${esc(addr)}<br><span style="color:#667085">${esc(r.refined || '')}</span><br>${r.lat.toFixed(6)}, ${r.lon.toFixed(6)}`);
  m.addTo(group);
  markers[i] = m;
}

function updateSummary() {
  const ok = results.filter(r => r && r.ok).length;
  const fail = results.filter(r => r && !r.ok).length;
  $('summary').textContent = `(성공 ${ok} / 실패 ${fail} / 전체 ${rows.length})`;
}

$('stop').addEventListener('click', () => { stopFlag = true; });

$('run').addEventListener('click', async () => {
  if (running || !rows.length) return;
  running = true; stopFlag = false;
  resetResults(); renderTable();
  $('run').disabled = true; $('stop').disabled = false;
  const col = +$('col').value, type = $('atype').value;
  const total = rows.length, cache = new Map();
  let next = 0, done = 0, errStreak = 0;
  $('prog').max = total;

  async function worker() {
    while (!stopFlag) {
      const i = next++; if (i >= total) return;
      const addr = String(rows[i][col] ?? '').trim();
      let r;
      if (!addr) r = { ok: false, error: '주소 없음' };
      else {
        if (!cache.has(addr)) cache.set(addr, fetchGeo(addr, type));
        r = await cache.get(addr);
      }
      results[i] = r; updateRow(i);
      if (r.ok) addMarker(i);
      done++; $('prog').value = done; $('progText').textContent = `${done}/${total}`;
      updateSummary();
      if (r.apiError) {
        errStreak++;
        if (errStreak >= 3) { stopFlag = true; showWarn('API 오류로 중단했습니다: ' + r.error); }
      } else errStreak = 0;
    }
  }
  await Promise.all([worker(), worker(), worker()]);

  running = false; $('run').disabled = false; $('stop').disabled = true;
  if (group.getLayers().length) map.fitBounds(group.getBounds().pad(0.15), { maxZoom: 17 });
  $('dlx').disabled = $('dlc').disabled = !results.some(r => r);
});

/* ---------- 저장 ---------- */
function buildAoa() {
  const out = [[...headers, '위도', '경도', '변환상태', '변환주소']];
  rows.forEach((r, i) => {
    const x = results[i];
    out.push([...r, x && x.ok ? x.lat : '', x && x.ok ? x.lon : '', x ? (x.ok ? '성공' : (x.error || '실패')) : '', x && x.ok ? (x.refined || '') : '']);
  });
  return out;
}
$('dlx').addEventListener('click', () => {
  const ws = XLSX.utils.aoa_to_sheet(buildAoa());
  const wb = XLSX.utils.book_new(); XLSX.utils.book_append_sheet(wb, ws, '변환결과');
  XLSX.writeFile(wb, 'geocode_result.xlsx');
});
$('dlc').addEventListener('click', () => {
  const csv = '﻿' + XLSX.utils.sheet_to_csv(XLSX.utils.aoa_to_sheet(buildAoa()));
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  a.download = 'geocode_result.csv'; a.click(); URL.revokeObjectURL(a.href);
});
</script>
</body>
</html>
'''

# ------------------------------------------------------------------ 실행


def main():
    if not API_KEY:
        print("[경고] VWORLD_API_KEY 가 비어 있습니다. .env 파일에 인증키를 입력하세요. (화면은 열리지만 변환은 되지 않습니다)")
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"실행 중: {url}   (종료: Ctrl+C)")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
