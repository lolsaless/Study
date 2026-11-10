#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
주소 → 위도·경도 변환기 v2 (브이월드 지오코더 + 주소·장소 검색 + 지도 표시)

사용법
  1) 이 파일과 같은 폴더의 .env 파일에 인증키를 적는다.
         VWORLD_API_KEY=발급받은_인증키
         # (선택) 카카오 REST API 키를 넣으면 검색이 카카오 기준으로도 동작
         # KAKAO_REST_API_KEY=카카오_REST_API_키
     (처음 실행하면 .env 템플릿과 .gitignore 항목이 자동으로 만들어진다)
  2) python geocoder_app.py   →  브라우저가 자동으로 열린다.
  3) 끝낼 때는 화면 오른쪽 위 [종료] 버튼 (또는 터미널에서 Ctrl+C)

자동 저장
  - Chrome/Edge 에서 [원본에 자동 저장하며 열기]로 .xlsx/.csv 를 열면, 변환할 때마다 그 원본 파일에 바로 반영된다.
    (열 때 원본 사본을 다운로드 폴더에 '백업_파일명' 으로 한 번 저장한다)
  - 붙여넣기, .xls, 다른 브라우저, [저장 없이 열기]는 이 폴더의 geocode_autosave.csv 에 자동 저장된다.

보안
  - 인증키는 .env 에만 있고 브라우저(HTML)로는 전달되지 않는다.
  - .env 는 .gitignore 에 자동 등록되어 깃허브에 올라가지 않는다.
  - 서버는 127.0.0.1(내 컴퓨터)에서만 접속 가능하고, 종료 요청은 실행 때마다 새로 만드는 토큰이 있어야 한다.

필요 패키지: 없음 (파이썬 표준 라이브러리만 사용)
"""
import csv
import json
import os
import secrets
import sys
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor
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
        "*.tmp",
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


ENV_TEMPLATE = (
    "# 브이월드 인증키 (이 파일은 절대 깃허브에 올리지 마세요)\n"
    "VWORLD_API_KEY=\n"
    "# 인증키 발급 시 입력한 서비스 URL 도메인이 필요하면 아래 주석 해제\n"
    "# VWORLD_DOMAIN=localhost\n"
    "# (선택) 카카오 REST API 키 — 있으면 주소·장소 검색이 카카오 데이터로도 동작\n"
    "# KAKAO_REST_API_KEY=\n"
    "# PORT=8000\n"
)


def ensure_env_template():
    try:
        if not ENV_PATH.exists():
            ENV_PATH.write_text(ENV_TEMPLATE, encoding="utf-8")
            print(f"[안내] {ENV_PATH.name} 템플릿을 만들었습니다. VWORLD_API_KEY= 뒤에 인증키를 붙여넣고 다시 실행하세요.")
        else:
            text = ENV_PATH.read_text(encoding="utf-8-sig")
            if "KAKAO_REST_API_KEY" not in text:  # 기존 .env 에 선택 항목 안내만 덧붙임 (기존 값은 건드리지 않음)
                with open(ENV_PATH, "a", encoding="utf-8") as f:
                    if not text.endswith("\n"):
                        f.write("\n")
                    f.write("# (선택) 카카오 REST API 키 — 있으면 주소·장소 검색이 카카오 데이터로도 동작\n# KAKAO_REST_API_KEY=\n")
    except OSError as e:
        print(f"[경고] .env 를 준비하지 못했습니다: {e}")


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
KAKAO_KEY = os.environ.get("KAKAO_REST_API_KEY", "").strip()
DOMAIN = os.environ.get("VWORLD_DOMAIN", "").strip()
PORT = int(os.environ.get("PORT", "8000") or 8000)
AUTOSAVE_NAME = "geocode_autosave.csv"
MAX_BODY = 60 * 1024 * 1024
SESSION_TOKEN = secrets.token_urlsafe(16)  # 종료 요청 확인용 (실행할 때마다 새로 생성)
SERVER = None


def scrub(text: str) -> str:
    """오류 메시지에 인증키가 섞여 나가지 않도록 가린다."""
    for k in (API_KEY, KAKAO_KEY):
        if k:
            text = text.replace(k, "***")
    return text


def http_json(url, headers=None, timeout=15):
    h = {"User-Agent": "Mozilla/5.0"}
    h.update(headers or {})
    with urlopen(Request(url, headers=h), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ------------------------------------------------------------------ 브이월드 지오코더

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

    try:
        data = http_json("https://api.vworld.kr/req/address?" + urlencode(params))
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


# ------------------------------------------------------------------ 주소·장소 검색


def _vworld_search_one(query, stype, category):
    params = {
        "service": "search",
        "request": "search",
        "version": "2.0",
        "crs": "EPSG:4326",
        "size": "5",
        "page": "1",
        "query": query,
        "type": stype,
        "format": "json",
        "errorformat": "json",
        "key": API_KEY,
    }
    if category:
        params["category"] = category
    if DOMAIN:
        params["domain"] = DOMAIN
    data = http_json("https://api.vworld.kr/req/search?" + urlencode(params))
    resp = data.get("response", {})
    status = resp.get("status")
    if status == "NOT_FOUND":
        return []
    if status != "OK":
        err = resp.get("error") or {}
        raise RuntimeError(f'{err.get("code", "")} {err.get("text", "")}'.strip() or "검색 API 오류")
    out = []
    for it in (resp.get("result") or {}).get("items", []):
        pt = it.get("point") or {}
        addr = it.get("address")
        if isinstance(addr, str):
            addr = {"parcel": addr}
        addr = addr or {}
        try:
            lat, lon = float(pt["y"]), float(pt["x"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append({
            "title": (it.get("title") or "") if stype == "place" else "",
            "road": addr.get("road", "") or "",
            "parcel": addr.get("parcel", "") or "",
            "lat": lat,
            "lon": lon,
            "src": "브이월드",
        })
    return out


def _kakao_search(query):
    headers = {"Authorization": "KakaoAK " + KAKAO_KEY}
    out = []
    d = http_json("https://dapi.kakao.com/v2/local/search/address.json?" + urlencode({"query": query, "size": 5}), headers)
    for doc in d.get("documents", []):
        road = (doc.get("road_address") or {}).get("address_name", "") or ""
        parcel = (doc.get("address") or {}).get("address_name", "") or ""
        if not parcel and not road:
            parcel = doc.get("address_name", "") or ""
        try:
            out.append({"title": "", "road": road, "parcel": parcel, "lat": float(doc["y"]), "lon": float(doc["x"]), "src": "카카오"})
        except (KeyError, TypeError, ValueError):
            continue
    d = http_json("https://dapi.kakao.com/v2/local/search/keyword.json?" + urlencode({"query": query, "size": 5}), headers)
    for doc in d.get("documents", []):
        try:
            out.append({
                "title": doc.get("place_name", "") or "",
                "road": doc.get("road_address_name", "") or "",
                "parcel": doc.get("address_name", "") or "",
                "lat": float(doc["y"]),
                "lon": float(doc["x"]),
                "src": "카카오",
            })
        except (KeyError, TypeError, ValueError):
            continue
    return out


def search_places(query: str) -> dict:
    jobs = []
    if API_KEY:
        jobs += [
            ("브이월드", lambda: _vworld_search_one(query, "address", "road")),
            ("브이월드", lambda: _vworld_search_one(query, "address", "parcel")),
            ("브이월드", lambda: _vworld_search_one(query, "place", None)),
        ]
    if KAKAO_KEY:
        jobs.append(("카카오", lambda: _kakao_search(query)))

    results, errors = [], []
    with ThreadPoolExecutor(max_workers=max(1, len(jobs))) as ex:
        futs = [(name, ex.submit(fn)) for name, fn in jobs]
        for name, fut in futs:
            try:
                results.append(fut.result())
            except Exception as e:
                errors.append(scrub(f"{name}: {type(e).__name__}: {e}"))

    # 카카오 → 브이월드 순으로 합치고 중복 제거
    order = sorted(results, key=lambda lst: 0 if lst and lst[0]["src"] == "카카오" else 1)
    seen, items = set(), []
    for lst in order:
        for it in lst:
            key = (round(it["lat"], 4), round(it["lon"], 4), it["title"] or it["parcel"] or it["road"])
            if key in seen:
                continue
            seen.add(key)
            items.append(it)
    return {
        "items": items[:12],
        "errors": sorted(set(errors)),
        "sources": (["브이월드"] if API_KEY else []) + (["카카오"] if KAKAO_KEY else []),
    }


# ------------------------------------------------------------------ 배경지도 타일(키를 서버에서만 사용)

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
    server_version = "GeoApp/2.0"

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

    def _host_ok(self):
        host = (self.headers.get("Host") or "").lower()
        return host in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, b"forbidden", "text/plain")
        u = urlparse(self.path)
        q = parse_qs(u.query)

        if u.path in ("/", "/index.html"):
            page = HTML.replace("__TOKEN__", SESSION_TOKEN)
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8", {"Cache-Control": "no-store"})

        elif u.path == "/api/status":
            self._json({"keyLoaded": bool(API_KEY), "kakao": bool(KAKAO_KEY)})

        elif u.path == "/api/geocode":
            address = (q.get("address", [""])[0] or "").strip()
            mode = q.get("type", ["auto"])[0]
            if not address:
                self._json({"ok": False, "error": "주소 없음"})
            else:
                self._json(geocode(address, mode if mode in ("auto", "road", "parcel") else "auto"))

        elif u.path == "/api/search":
            query = (q.get("q", [""])[0] or "").strip()
            if len(query) < 2:
                self._json({"items": [], "errors": [], "sources": []})
            elif not API_KEY and not KAKAO_KEY:
                self._json({"items": [], "errors": [".env 에 VWORLD_API_KEY 가 설정되지 않았습니다."], "sources": []})
            else:
                self._json(search_places(query))

        elif u.path.startswith("/tile/"):
            parts = u.path.split("/")  # ['', 'tile', layer, z, y, x]
            if len(parts) == 6 and parts[2] in TILE_EXT and all(p.isdigit() for p in parts[3:]) and API_KEY:
                try:
                    body, ctype = fetch_tile(parts[2], parts[3], parts[4], parts[5])
                    self._send(200, body, ctype, {"Cache-Control": "public, max-age=86400"})
                except Exception:
                    self._send(404, b"", "text/plain")
            else:
                self._send(404, b"", "text/plain")

        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if not self._host_ok():
            return self._send(403, b"forbidden", "text/plain")
        if urlparse(self.path).path == "/api/shutdown":
            token = self.headers.get("X-Token", "")
            if not secrets.compare_digest(token, SESSION_TOKEN):
                return self._json({"ok": False, "error": "forbidden"}, 403)
            self._json({"ok": True})
            if SERVER is not None:
                threading.Timer(0.4, SERVER.shutdown).start()
        elif urlparse(self.path).path == "/api/autosave":
            token = self.headers.get("X-Token", "")
            if not secrets.compare_digest(token, SESSION_TOKEN):
                return self._json({"ok": False, "error": "forbidden"}, 403)
            try:
                n = int(self.headers.get("Content-Length", "0"))
                if n <= 0 or n > MAX_BODY:
                    return self._json({"ok": False, "error": "본문 크기 오류"}, 413)
                data = json.loads(self.rfile.read(n).decode("utf-8"))
                rows = data.get("rows")
                if not isinstance(rows, list):
                    raise ValueError("rows 형식 오류")
                out = BASE_DIR / AUTOSAVE_NAME
                tmp = BASE_DIR / (AUTOSAVE_NAME + ".tmp")
                with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
                    w = csv.writer(f)
                    for r in rows:
                        w.writerow(["" if c is None else c for c in r])
                os.replace(tmp, out)
                self._json({"ok": True, "file": AUTOSAVE_NAME})
            except Exception as e:
                self._json({"ok": False, "error": scrub(f"{type(e).__name__}: {e}")}, 500)
        else:
            self._send(404, b"not found", "text/plain")


# ------------------------------------------------------------------ 화면(HTML) — Linear 디자인 시스템 기반 다크 테마

HTML = r'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>주소 변환기</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
  :root {
    --canvas: #010102; --s1: #0f1011; --s2: #141516; --s3: #18191a; --s4: #191a1b;
    --hair: #23252a; --hair2: #34343a; --hair3: #3e3e44;
    --ink: #f7f8f8; --ink2: #d0d6e0; --ink3: #8a8f98; --ink4: #62666d;
    --primary: #5e6ad2; --primary-h: #828fff; --primary-f: #5e69d1;
    --ok: #27a644; --danger: #d9686e;
    --font: "Inter", "SF Pro Display", -apple-system, system-ui, "Segoe UI", "Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans KR", sans-serif;
    --mono: ui-monospace, "SF Mono", Menlo, Consolas, "JetBrains Mono", monospace;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; background: var(--canvas); color: var(--ink); font-family: var(--font); font-size: 14px; line-height: 1.5; -webkit-font-smoothing: antialiased; }
  body { display: flex; flex-direction: column; }
  ::selection { background: rgba(94,106,210,.45); }

  /* top nav */
  #top { height: 56px; flex: none; display: flex; align-items: center; gap: 12px; padding: 0 20px; background: var(--canvas); border-bottom: 1px solid var(--hair); }
  .mark { width: 14px; height: 14px; border-radius: 50%; border: 3px solid var(--primary); }
  .brand { font-weight: 600; letter-spacing: -0.2px; font-size: 15px; }
  .pill { background: var(--s2); color: var(--ink2); font-size: 12px; padding: 2px 8px; border-radius: 9999px; border: 1px solid var(--hair); }
  .spacer { flex: 1; }

  /* layout */
  :root { --side: min(56vw, 980px); }
  #app { flex: 1; min-height: 0; display: grid; grid-template-columns: var(--side) 9px minmax(0, 1fr); }
  aside { display: flex; flex-direction: column; gap: 12px; padding: 16px; min-height: 0; min-width: 0; overflow: hidden; }
  #split { position: relative; cursor: col-resize; touch-action: none; outline: none; }
  #split::after { content: ""; position: absolute; left: 4px; top: 0; bottom: 0; width: 1px; background: var(--hair); }
  #split:hover::after, #split.drag::after, #split:focus-visible::after { background: var(--hair3); left: 3px; width: 3px; border-radius: 2px; }
  main { position: relative; min-height: 0; }
  #map { height: 100%; width: 100%; background: var(--s1); }

  .card { background: var(--s1); border: 1px solid var(--hair); border-radius: 12px; padding: 16px; }
  .eyebrow { font-size: 13px; font-weight: 500; letter-spacing: .4px; color: var(--ink3); margin: 0 0 10px; }
  .row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 10px; }
  .muted { color: var(--ink3); }
  .small { font-size: 12px; }
  .mono { font-family: var(--mono); font-size: 12.5px; }

  /* controls */
  .btn { font: 500 14px/1.2 var(--font); padding: 8px 14px; border-radius: 8px; border: 1px solid var(--hair); background: var(--s1); color: var(--ink); cursor: pointer; transition: background .12s, border-color .12s; }
  .btn:hover:not(:disabled) { background: var(--s3); border-color: var(--hair2); }
  .btn.primary { background: var(--primary); border-color: var(--primary); color: #fff; }
  .btn.primary:hover:not(:disabled) { background: var(--primary-h); border-color: var(--primary-h); }
  .btn.primary:active:not(:disabled) { background: var(--primary-f); }
  .btn:disabled { color: var(--ink4); cursor: default; }
  .btn.primary:disabled { background: var(--s3); border-color: var(--hair); color: var(--ink4); }
  .btn.sm { padding: 5px 10px; font-size: 13px; }
  .mini { font: 500 13px/1 var(--font); padding: 4px 8px; border-radius: 6px; border: 1px solid var(--hair); background: var(--s2); color: var(--ink2); cursor: pointer; }
  .mini:hover { background: var(--s3); border-color: var(--hair2); }
  input[type=text], input:not([type]), select, textarea { font: 14px/1.4 var(--font); background: var(--s1); color: var(--ink); border: 1px solid var(--hair); border-radius: 8px; padding: 8px 12px; }
  select { padding: 6px 10px; }
  select option { background: var(--s2); color: var(--ink); }
  textarea { width: 100%; height: 84px; resize: vertical; }
  textarea::placeholder, input::placeholder { color: var(--ink4); }
  input:focus-visible, select:focus-visible, textarea:focus-visible, button:focus-visible { outline: 2px solid rgba(94,105,209,.5); outline-offset: 1px; border-color: var(--hair2); }
  input[type=file] { font-size: 13px; color: var(--ink2); max-width: 100%; }
  input[type=file]::file-selector-button { font: 500 13px var(--font); padding: 6px 12px; margin-right: 10px; border-radius: 8px; border: 1px solid var(--hair); background: var(--s2); color: var(--ink); cursor: pointer; }
  input[type=file]::file-selector-button:hover { background: var(--s3); }
  input[type=checkbox] { accent-color: var(--primary); }
  label { color: var(--ink2); }
  progress { appearance: none; -webkit-appearance: none; flex: 1; min-width: 120px; height: 6px; border: 0; border-radius: 9999px; background: var(--hair); overflow: hidden; }
  progress::-webkit-progress-bar { background: var(--hair); }
  progress::-webkit-progress-value { background: var(--primary); }
  progress::-moz-progress-bar { background: var(--primary); }

  .warn { background: var(--s2); border: 1px solid var(--hair2); color: var(--ink2); padding: 10px 12px; border-radius: 8px; font-size: 13px; }

  /* result table */
  #result { flex: 1; min-height: 0; display: flex; flex-direction: column; }
  #tbl { flex: 1; min-height: 0; overflow: auto; margin-top: 10px; border: 1px solid var(--hair); border-radius: 8px; background: var(--canvas); }
  #tbl.busy { pointer-events: none; opacity: .7; }
  table { border-collapse: collapse; width: max-content; min-width: 100%; font-size: 13px; }
  th, td { border-bottom: 1px solid var(--hair); padding: 5px 10px; text-align: left; white-space: nowrap; max-width: 220px; overflow: hidden; text-overflow: ellipsis; }
  th { position: sticky; top: 0; z-index: 1; background: var(--s2); color: var(--ink3); font-weight: 500; font-size: 12px; }
  th .tag { background: var(--s4); border: 1px solid var(--hair2); border-radius: 9999px; padding: 0 6px; margin-left: 4px; color: var(--ink2); }
  td.n, th.n { color: var(--ink4); width: 1%; }
  td.ac { min-width: 230px; max-width: none; padding: 3px 6px; }
  td.ac input { width: 100%; min-width: 220px; padding: 4px 8px; background: var(--s1); font-size: 13px; }
  tbody tr { cursor: pointer; }
  tbody tr:hover { background: var(--s2); }
  tbody tr.sel { background: var(--s3); box-shadow: inset 2px 0 0 var(--ink3); }
  tr.ok .st { color: var(--ok); }
  tr.fail .st { color: var(--danger); }
  tr.busyrow .st { color: var(--ink3); }
  td.act { width: 1%; }
  tr.edited td.ac input { border-color: var(--hair3); }
  .cardhead { display: flex; align-items: center; justify-content: space-between; }
  .cardhead .eyebrow { margin: 0 0 10px; }
  #inBox[hidden] { display: none; }
  .seg { display: inline-flex; gap: 2px; background: var(--canvas); border: 1px solid var(--hair); border-radius: 9999px; padding: 2px; }
  .seg button { font: 500 13px/1.2 var(--font); border: 0; background: transparent; color: var(--ink3); padding: 5px 12px; border-radius: 9999px; cursor: pointer; }
  .seg button:hover { color: var(--ink); }
  .seg button.on { background: var(--s3); color: var(--ink); }
  .seg i { font-style: normal; color: var(--ink4); margin-left: 4px; }
  .seg button.on i { color: var(--ink3); }
  #tbl.f-fail tr[data-i]:not(.fail):not(.sel), #tbl.f-ok tr[data-i]:not(.ok):not(.sel), #tbl.f-edit tr[data-i]:not(.edited):not(.sel) { display: none; }
  #saveState.err { color: var(--danger); }

  /* map search overlay */
  #searchbar { position: absolute; top: 12px; left: 56px; z-index: 1000; width: min(500px, calc(100% - 72px)); }
  #searchbar .box { background: var(--s1); border: 1px solid var(--hair2); border-radius: 12px; padding: 10px; }
  #searchbar .line { display: flex; gap: 8px; align-items: center; }
  #q { flex: 1; min-width: 0; }
  #selInfo { margin: 8px 2px 0; font-size: 12px; color: var(--ink3); }
  #sres { margin-top: 8px; max-height: 46vh; overflow: auto; border-top: 1px solid var(--hair); }
  .item { padding: 8px 6px; border-bottom: 1px solid var(--hair); cursor: pointer; border-radius: 6px; }
  .item:hover { background: var(--s3); }
  .item .t { font-weight: 500; color: var(--ink); }
  .item .s { font-size: 12px; color: var(--ink3); }
  .item .src { float: right; font-size: 11px; color: var(--ink2); background: var(--s2); border: 1px solid var(--hair); border-radius: 9999px; padding: 0 7px; }
  .empty { padding: 10px 6px; color: var(--ink3); font-size: 13px; }

  /* leaflet dark skin */
  .dark-tiles { filter: invert(1) hue-rotate(180deg) brightness(.88) contrast(.92) saturate(.55); }
  .leaflet-bar a, .leaflet-bar a:hover { background: var(--s1); color: var(--ink); border-bottom-color: var(--hair); }
  .leaflet-bar a:hover { background: var(--s3); }
  .leaflet-bar { border: 1px solid var(--hair2); box-shadow: none; }
  .leaflet-control-layers { background: var(--s1); color: var(--ink); border: 1px solid var(--hair2); box-shadow: none; border-radius: 8px; }
  .leaflet-control-layers-toggle { background-color: var(--s1); }
  .leaflet-container a { color: var(--primary-h); }
  .leaflet-control-attribution { background: rgba(1,1,2,.7) !important; color: var(--ink3) !important; }
  .leaflet-popup-content-wrapper, .leaflet-popup-tip { background: var(--s2); color: var(--ink); border: 1px solid var(--hair2); box-shadow: none; }
  .leaflet-popup-content-wrapper { border-radius: 8px; }
  .leaflet-popup-content { margin: 10px 14px; font-family: var(--font); font-size: 13px; }
  .leaflet-container a.leaflet-popup-close-button { color: var(--ink3); }

  #toast { position: fixed; left: 50%; bottom: 20px; transform: translateX(-50%); background: var(--s3); border: 1px solid var(--hair2); color: var(--ink); padding: 8px 14px; border-radius: 9999px; font-size: 13px; z-index: 3000; opacity: 0; pointer-events: none; transition: opacity .2s; }
  #toast.show { opacity: 1; }
  #bye { position: fixed; inset: 0; z-index: 5000; background: var(--canvas); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; }
  #bye[hidden], #sres[hidden], .warn[hidden] { display: none; }
  #bye h2 { font-size: 28px; font-weight: 600; letter-spacing: -0.6px; margin: 0; }

  @media (max-width: 900px) { #app { grid-template-columns: 1fr; grid-template-rows: 55% 45%; } #split { display: none; } }
</style>
</head>
<body>
<header id="top">
  <span class="mark"></span>
  <span class="brand">주소 변환기</span>
  <span class="pill">VWorld</span>
  <span class="spacer"></span>
  <button id="quit" class="btn" title="프로그램(로컬 서버)을 종료합니다">종료</button>
</header>

<div id="app">
  <aside>
    <div id="warn" class="warn" hidden></div>

    <section class="card">
      <div class="cardhead"><p class="eyebrow">1 · 주소 입력</p><button id="foldIn" class="mini">접기</button></div>
      <div id="inBox">
        <div class="row" style="margin-top:0">
          <button id="openFS" class="btn sm" title="Chrome/Edge: 선택한 원본 파일에 변환 결과를 바로바로 저장합니다">원본에 자동 저장하며 열기</button>
          <span class="muted small">또는 저장 없이 열기</span>
          <input type="file" id="file" accept=".xlsx,.xls,.csv">
        </div>
        <div class="row small muted" style="margin-top:8px">엑셀에서 복사해 붙여넣어도 됩니다 (주소 열만 / 여러 열 모두 가능)</div>
        <textarea id="paste" placeholder="서울특별시 중구 세종대로 110&#10;경기도 수원시 팔달구 효원로 1" style="margin-top:6px"></textarea>
      </div>
      <div class="row">
        <label><input type="checkbox" id="hasHeader" checked> 첫 행은 머리글</label>
        <label>주소 열 <select id="col"></select></label>
        <label>유형
          <select id="atype">
            <option value="auto">자동 (도로명→지번)</option>
            <option value="road">도로명</option>
            <option value="parcel">지번</option>
          </select>
        </label>
      </div>
      <div class="row">
        <button id="run" class="btn primary" disabled>변환 시작</button>
        <button id="stop" class="btn" disabled>중지</button>
        <progress id="prog" value="0" max="1"></progress>
        <span id="progText" class="muted small"></span>
      </div>
    </section>

    <section class="card" id="result">
      <p class="eyebrow">2 · 결과 · 수정 <span id="summary"></span></p>
      <div class="row" style="margin-top:0">
        <div class="seg" id="flt">
          <button data-f="all" class="on">전체<i>0</i></button>
          <button data-f="fail">실패<i>0</i></button>
          <button data-f="ok">성공<i>0</i></button>
          <button data-f="edit">수정<i>0</i></button>
        </div>
        <button id="nextFail" class="btn sm" title="다음 실패 행을 선택하고 검색 후보를 보여줍니다">다음 실패 ▶</button>
        <span class="spacer"></span>
        <button id="dlx" class="btn sm" disabled>엑셀로 저장</button>
        <button id="dlc" class="btn sm" disabled>CSV로 저장</button>
      </div>
      <div class="row small" style="margin-top:8px">
        <label><input type="checkbox" id="auto" checked> 자동 저장</label>
        <span id="saveState" class="muted"></span>
      </div>
      <div class="muted small" style="margin-top:6px">주소 칸을 고치고 Enter → 다시 조회 · 실패한 행을 선택하면 지도 위 검색창이 후보를 보여줍니다</div>
      <div id="tbl"></div>
    </section>
  </aside>
  <div id="split" role="separator" aria-orientation="vertical" tabindex="0" title="드래그해서 좌우 폭 조절 · 더블클릭: 기본값 · 방향키: 미세 조절"></div>

  <main>
    <div id="map"></div>
    <div id="searchbar">
      <div class="box">
        <div class="line">
          <input id="q" type="text" placeholder="주소·장소 검색 (예: 효원로 1, 수원시청)" autocomplete="off">
          <select id="fmt" title="검색 결과를 선택행에 적용할 때 쓸 주소 형식">
            <option value="parcel">지번 우선</option>
            <option value="road">도로명 우선</option>
          </select>
          <button id="qgo" class="btn sm">검색</button>
        </div>
        <div id="selInfo">행을 선택하면 검색 결과를 그 행의 주소·좌표로 바로 적용할 수 있습니다.</div>
        <div id="sres" hidden></div>
      </div>
    </div>
  </main>
</div>

<div id="toast"></div>
<div id="bye" hidden>
  <h2>종료되었습니다</h2>
  <div class="muted">로컬 서버가 꺼졌습니다. 이 탭은 닫아도 됩니다.</div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"></script>
<script>
const TOKEN = '__TOKEN__';
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

let raw = [], headers = [], rows = [], orig = [], results = [], markers = [];
let selected = -1, dirty = false, running = false, stopFlag = false, kakaoOn = false;
let wb = null, sheetName = '', rawSrc = [], sheetC0 = 0, sheetEndC = 0;
let fileHandle = null, fileName = '', fileKind = '';
let saving = false, saveAgain = false, saveTimer = null, lastSaveAt = 0;
const colIdx = () => +$('col').value;

function toast(msg) { const t = $('toast'); t.textContent = msg; t.classList.add('show'); clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove('show'), 2200); }
function showWarn(msg) { const w = $('warn'); w.textContent = msg; w.hidden = false; }
function markDirty() { dirty = true; scheduleSave(); }

/* ---------- 지도 ---------- */
const map = L.map('map', { preferCanvas: true, zoomControl: true }).setView([36.5, 127.8], 7);
const vDark = L.tileLayer('/tile/Base/{z}/{y}/{x}', { maxZoom: 19, className: 'dark-tiles', attribution: '© VWorld' }).addTo(map);
const vBase = L.tileLayer('/tile/Base/{z}/{y}/{x}', { maxZoom: 19, attribution: '© VWorld' });
const vSat  = L.tileLayer('/tile/Satellite/{z}/{y}/{x}', { maxZoom: 19, attribution: '© VWorld' });
const vHyb  = L.tileLayer('/tile/Hybrid/{z}/{y}/{x}', { maxZoom: 19 });
const osm   = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, className: 'dark-tiles', attribution: '© OpenStreetMap' });
L.control.layers({ 'VWorld 다크': vDark, 'VWorld 일반': vBase, 'VWorld 위성': vSat, 'OpenStreetMap': osm }, { '지명 표시(위성 위)': vHyb }).addTo(map);
const group = L.featureGroup().addTo(map);
let tempMarker = null;

let tileOk = 0, tileErr = 0;
vDark.on('tileload', () => tileOk++);
vDark.on('tileerror', () => {
  tileErr++;
  if (tileOk === 0 && tileErr >= 6 && map.hasLayer(vDark)) {
    map.removeLayer(vDark); osm.addTo(map);
    showWarn('브이월드 배경지도를 불러오지 못해 OpenStreetMap으로 전환했습니다. (인증키의 배경지도 API 선택 여부·서비스 URL 확인)');
  }
});

const MS = {
  normal: { radius: 7, color: '#010102', weight: 2, fillColor: '#5e6ad2', fillOpacity: 0.95 },
  sel:    { radius: 10, color: '#f7f8f8', weight: 3, fillColor: '#5e6ad2', fillOpacity: 1 }
};

fetch('/api/status').then(r => r.json()).then(s => {
  kakaoOn = !!s.kakao;
  if (!s.keyLoaded) showWarn('.env 파일에 VWORLD_API_KEY 가 설정되어 있지 않습니다. 인증키를 넣고 프로그램을 다시 실행하세요.');
}).catch(() => {});

/* ---------- 입력 처리 ---------- */
$('file').addEventListener('change', e => { const f = e.target.files[0]; if (f) loadFile(f, null); });

$('paste').addEventListener('input', () => {
  $('file').value = '';
  wb = null; fileHandle = null; fileName = ''; fileKind = ''; rawSrc = [];
  raw = $('paste').value.split(/\r?\n/).filter(l => l.trim() !== '').map(l => l.split('\t'));
  $('hasHeader').checked = false;   // 붙여넣기는 기본적으로 머리글 없음으로 간주
  afterLoad();
});
$('hasHeader').addEventListener('change', afterLoad);
$('col').addEventListener('change', () => { captureOrig(); resetResults(); renderTable(); });

function afterLoad() {
  buildTable(); resetResults(); renderTable(); setFilter('all'); updateSaveLabel();
  dirty = false;
  $('run').disabled = rows.length === 0;
  $('summary').textContent = rows.length ? `· ${rows.length}건 대기` : '';
}

function captureOrig() { const c = colIdx(); orig = rows.map(r => r[c]); }

function buildTable() {
  if (!raw.length) { headers = []; rows = []; orig = []; $('col').innerHTML = ''; return; }
  const n = raw.reduce((m, r) => Math.max(m, r.length), 0);
  const norm = raw.map(r => Array.from({ length: n }, (_, i) => String(r[i] ?? '').trim()));
  const hh = $('hasHeader').checked;
  headers = hh ? norm[0].map((h, i) => h || ('열 ' + (i + 1))) : norm[0].map((_, i) => '열 ' + (i + 1));
  rows = hh ? norm.slice(1) : norm;
  $('col').innerHTML = headers.map((h, i) => `<option value="${i}">${esc(h)}</option>`).join('');
  let idx = headers.findIndex(h => /주소|소재지|address/i.test(h));
  $('col').value = idx < 0 ? 0 : idx;
  captureOrig();
}

function resetResults() {
  results = rows.map(() => null);
  markers = []; selected = -1;
  group.clearLayers();
  if (tempMarker) { map.removeLayer(tempMarker); tempMarker = null; }
  $('prog').value = 0; $('progText').textContent = '';
  $('dlx').disabled = true; $('dlc').disabled = true;
  $('selInfo').textContent = '행을 선택하면 검색 결과를 그 행의 주소·좌표로 바로 적용할 수 있습니다.';
}

const isEdited = i => rows[i][colIdx()] !== orig[i];
function statusText(i) {
  const r = results[i];
  if (!r) return '';
  if (r.pending) return '조회 중…';
  if (r.ok) return isEdited(i) ? (r.via === 'search' ? '성공 · 검색 적용' : '성공 · 수정 후 조회') : '성공';
  return r.error || '실패';
}

function renderTable() {
  if (!rows.length) { $('tbl').innerHTML = ''; return; }
  const c = colIdx();
  let h = '<table><thead><tr><th class="n">#</th>' +
    headers.map((x, j) => `<th>${esc(x)}${j === c ? '<span class="tag">주소</span>' : ''}</th>`).join('') +
    '<th>위도</th><th>경도</th><th>상태</th><th></th></tr></thead><tbody>';
  rows.forEach((r, i) => {
    h += `<tr id="r${i}" data-i="${i}"><td class="n">${i + 1}</td>` +
      r.map((v, j) => j === c
        ? `<td class="ac"><input class="addr" data-i="${i}" value="${esc(v)}" spellcheck="false"></td>`
        : `<td title="${esc(v)}">${esc(v)}</td>`).join('') +
      '<td class="lat mono"></td><td class="lon mono"></td><td class="st"></td><td class="act"><button class="mini" data-act="re" title="이 주소로 다시 조회">↻</button></td></tr>';
  });
  $('tbl').innerHTML = h + '</tbody></table>';
}

function updateRow(i) {
  const r = results[i], tr = $('r' + i); if (!tr) return;
  tr.querySelector('.lat').textContent = r && r.ok ? r.lat.toFixed(6) : '';
  tr.querySelector('.lon').textContent = r && r.ok ? r.lon.toFixed(6) : '';
  const st = tr.querySelector('.st'); st.textContent = statusText(i); st.title = st.textContent;
  tr.classList.remove('ok', 'fail', 'busyrow');
  if (r) tr.classList.add(r.pending ? 'busyrow' : (r.ok ? 'ok' : 'fail'));
  tr.classList.toggle('edited', isEdited(i));
}

function updateSummary() {
  const ok = results.filter(r => r && r.ok).length;
  const fail = results.filter(r => r && !r.ok && !r.pending).length;
  const ed = rows.filter((_, i) => isEdited(i)).length;
  $('summary').textContent = rows.length ? `· 전체 ${rows.length}건` : '';
  const cnt = { all: rows.length, fail, ok, edit: ed };
  document.querySelectorAll('#flt button').forEach(b => { b.querySelector('i').textContent = cnt[b.dataset.f]; });
  const any = results.some(r => r && !r.pending);
  $('dlx').disabled = $('dlc').disabled = !any;
}

/* ---------- 마커 ---------- */
function setMarker(i) {
  if (markers[i]) { group.removeLayer(markers[i]); markers[i] = null; }
  const r = results[i];
  if (!r || !r.ok) return;
  const addr = rows[i][colIdx()];
  const m = L.circleMarker([r.lat, r.lon], i === selected ? MS.sel : MS.normal);
  m.bindPopup(`<b>#${i + 1}</b><br>${esc(addr)}<br><span style="color:#8a8f98">${esc(r.refined || '')}</span><br><span class="mono">${r.lat.toFixed(6)}, ${r.lon.toFixed(6)}</span>`);
  m.on('click', () => selectRow(i, false));
  m.addTo(group);
  markers[i] = m;
}

/* ---------- 행 선택 ---------- */
function selectRow(i, fly = true) {
  if (i === selected && !fly) return;
  if (selected >= 0) { $('r' + selected)?.classList.remove('sel'); markers[selected]?.setStyle(MS.normal); }
  selected = i;
  const tr = $('r' + i); if (!tr) return;
  tr.classList.add('sel'); tr.scrollIntoView({ block: 'nearest' });
  markers[i]?.setStyle(MS.sel).bringToFront();
  const addr = rows[i][colIdx()];
  $('selInfo').innerHTML = `<b style="color:var(--ink)">#${i + 1}행 선택됨</b> — 검색 결과를 클릭하면 이 행의 주소와 좌표가 교체됩니다.`;
  if (fly && markers[i]) map.setView(markers[i].getLatLng(), Math.max(map.getZoom(), 16));
  if (document.activeElement !== $('q')) $('q').value = addr;
  const failed = !results[i] || !results[i].ok;
  if (failed && addr) runSearch(addr);
}

$('tbl').addEventListener('focusin', e => {
  const tr = e.target.closest('tr[data-i]'); if (tr) selectRow(+tr.dataset.i, false);
});
$('tbl').addEventListener('click', e => {
  const btn = e.target.closest('button[data-act="re"]');
  const tr = e.target.closest('tr[data-i]'); if (!tr) return;
  const i = +tr.dataset.i;
  if (btn) { geocodeRow(i); return; }
  if (e.target.tagName !== 'INPUT') selectRow(i, true);
});
$('tbl').addEventListener('change', e => {
  const inp = e.target.closest('input.addr'); if (!inp) return;
  const i = +inp.dataset.i;
  rows[i][colIdx()] = inp.value.trim();
  markDirty();
  geocodeRow(i);
});

/* ---------- 변환 ---------- */
async function fetchGeo(addr, type) {
  try {
    const res = await fetch('/api/geocode?' + new URLSearchParams({ address: addr, type }));
    return await res.json();
  } catch (e) { return { ok: false, apiError: true, error: '로컬 서버에 연결할 수 없습니다.' }; }
}

async function geocodeRow(i) {
  const addr = String(rows[i][colIdx()] ?? '').trim();
  if (!addr) { results[i] = { ok: false, error: '주소 없음' }; setMarker(i); updateRow(i); updateSummary(); return; }
  results[i] = { pending: true }; updateRow(i);
  const r = await fetchGeo(addr, $('atype').value);
  r.via = 'api';
  results[i] = r;
  setMarker(i); updateRow(i); updateSummary(); markDirty();
  if (r.ok) {
    if (i === selected) markers[i]?.setStyle(MS.sel).bringToFront();
    map.setView([r.lat, r.lon], Math.max(map.getZoom(), 16));
  } else if (i === selected) {
    $('q').value = addr; runSearch(addr);   // 실패하면 바로 검색 후보 제시
  }
}

$('stop').addEventListener('click', () => { stopFlag = true; });

$('run').addEventListener('click', async () => {
  if (running || !rows.length) return;
  running = true; stopFlag = false;
  resetResults(); renderTable();
  $('run').disabled = true; $('stop').disabled = false; $('tbl').classList.add('busy');
  const col = colIdx(), type = $('atype').value;
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
        r = Object.assign({}, await cache.get(addr));
      }
      r.via = 'api';
      results[i] = r; updateRow(i); setMarker(i);
      done++; $('prog').value = done; $('progText').textContent = `${done}/${total}`;
      updateSummary();
      if (Date.now() - lastSaveAt > 4000) doSave();
      if (r.apiError) {
        errStreak++;
        if (errStreak >= 3) { stopFlag = true; showWarn('API 오류로 중단했습니다: ' + r.error); }
      } else errStreak = 0;
    }
  }
  await Promise.all([worker(), worker(), worker()]);

  running = false; $('run').disabled = false; $('stop').disabled = true; $('tbl').classList.remove('busy');
  markDirty(); doSave();
  if (group.getLayers().length) map.fitBounds(group.getBounds().pad(0.15), { maxZoom: 17 });
});

/* ---------- 주소·장소 검색 ---------- */
let sTimer = null, sSeq = 0, sItems = [];
function hideResults() { $('sres').hidden = true; }

function runSearch(q) {
  q = (q || '').trim();
  if (q.length < 2) { hideResults(); return; }
  const seq = ++sSeq;
  $('sres').hidden = false; $('sres').innerHTML = '<div class="empty">검색 중…</div>';
  fetch('/api/search?' + new URLSearchParams({ q }))
    .then(r => r.json())
    .then(d => { if (seq === sSeq) renderSearch(d); })
    .catch(() => { if (seq === sSeq) $('sres').innerHTML = '<div class="empty">검색 서버에 연결할 수 없습니다.</div>'; });
}

function renderSearch(d) {
  sItems = d.items || [];
  let h = '';
  if (!sItems.length) {
    h = '<div class="empty">검색 결과가 없습니다. 표현을 줄이거나(예: 동 이름+번지, 건물명) 다른 키워드로 검색해 보세요.' +
        (d.errors && d.errors.length ? '<br>' + d.errors.map(esc).join('<br>') : '') + '</div>';
  } else {
    h = sItems.map((it, k) => {
      const t = it.title || it.parcel || it.road;
      const sub = [it.parcel && ('지번 ' + it.parcel), it.road && ('도로명 ' + it.road)].filter(Boolean).join(' · ');
      return `<div class="item" data-k="${k}"><span class="src">${esc(it.src)}</span><div class="t">${esc(t)}</div><div class="s">${esc(sub)}</div></div>`;
    }).join('');
  }
  if (!kakaoOn) h += '<div class="empty small">브이월드 검색만 사용 중 · 카카오 키(KAKAO_REST_API_KEY)를 .env 에 넣으면 카카오 기준으로도 검색됩니다.</div>';
  $('sres').innerHTML = h;
}

$('q').addEventListener('input', () => { clearTimeout(sTimer); sTimer = setTimeout(() => runSearch($('q').value), 400); });
$('q').addEventListener('keydown', e => {
  if (e.key === 'Enter') { clearTimeout(sTimer); runSearch($('q').value); }
  if (e.key === 'Escape') hideResults();
});
$('qgo').addEventListener('click', () => runSearch($('q').value));
map.on('click', hideResults);
L.DomEvent.disableClickPropagation($('searchbar'));
L.DomEvent.disableScrollPropagation($('searchbar'));

$('sres').addEventListener('click', e => {
  const el = e.target.closest('.item'); if (!el) return;
  chooseItem(sItems[+el.dataset.k]);
});

function chooseItem(it) {
  if (!it) return;
  if (selected >= 0) applyToRow(selected, it); else showTemp(it);
}

function applyToRow(i, it) {
  const c = colIdx(), pref = $('fmt').value;
  let a = pref === 'parcel' ? (it.parcel || it.road) : (it.road || it.parcel);
  a = a || it.title || '';
  rows[i][c] = a;
  const inp = document.querySelector(`#r${i} input.addr`); if (inp) inp.value = a;
  results[i] = { ok: true, lat: it.lat, lon: it.lon, refined: a, via: 'search' };
  setMarker(i); updateRow(i); updateSummary(); markDirty();
  markers[i]?.setStyle(MS.sel).bringToFront();
  map.setView([it.lat, it.lon], Math.max(map.getZoom(), 16));
  hideResults();
  toast(`#${i + 1}행에 적용했습니다: ${a}`);
}

function showTemp(it) {
  if (tempMarker) map.removeLayer(tempMarker);
  tempMarker = L.circleMarker([it.lat, it.lon], { radius: 11, color: '#f7f8f8', weight: 3, fillColor: '#010102', fillOpacity: 0.3 }).addTo(map);
  tempMarker.bindPopup(`${esc(it.title || '')}<br>${esc(it.parcel || '')}<br>${esc(it.road || '')}`).openPopup();
  map.setView([it.lat, it.lon], 17);
  hideResults();
}

/* ---------- 저장 ---------- */
function buildAoa(forOriginal = false) {
  // forOriginal: 자동 저장용 — 머리글이 없던 파일에는 머리글 행을 만들지 않고, 원본주소 열을 항상 둔다
  const hh = $('hasHeader').checked;
  const anyEdit = rows.some((_, i) => isEdited(i));
  const withOrig = forOriginal || anyEdit;
  const head = [...headers, '위도', '경도', '변환상태', '변환주소'];
  if (withOrig) head.push('원본주소');
  const out = [];
  if (!(forOriginal && !hh)) out.push(head);
  rows.forEach((r, i) => {
    const x = results[i], done = x && !x.pending;
    const line = [...r, done && x.ok ? x.lat : '', done && x.ok ? x.lon : '', done ? statusText(i) : '', done && x.ok ? (x.refined || '') : ''];
    if (withOrig) line.push(isEdited(i) ? orig[i] : '');
    out.push(line);
  });
  return out;
}$('dlx').addEventListener('click', () => {
  const ws = XLSX.utils.aoa_to_sheet(buildAoa());
  const wb = XLSX.utils.book_new(); XLSX.utils.book_append_sheet(wb, ws, '변환결과');
  XLSX.writeFile(wb, 'geocode_result.xlsx');
  dirty = false; toast('geocode_result.xlsx 로 저장했습니다.');
});
$('dlc').addEventListener('click', () => {
  const csv = '﻿' + XLSX.utils.sheet_to_csv(XLSX.utils.aoa_to_sheet(buildAoa()));
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  a.download = 'geocode_result.csv'; a.click(); URL.revokeObjectURL(a.href);
  dirty = false; toast('geocode_result.csv 로 저장했습니다.');
});

/* ---------- 파일 열기 · 원본 자동 저장 ---------- */
async function loadFile(f, handle) {
  try {
    const buf = await f.arrayBuffer();
    const isCsv = /\.csv$/i.test(f.name);
    if (isCsv) {
      let text;
      try { text = new TextDecoder('utf-8', { fatal: true }).decode(buf); }
      catch (_) { text = new TextDecoder('euc-kr').decode(buf); }   // CP949 CSV 대응
      wb = XLSX.read(text, { type: 'string' });
    } else {
      wb = XLSX.read(buf, { type: 'array' });
    }
    sheetName = wb.SheetNames[0];
    const ws = wb.Sheets[sheetName];
    const rng = ws['!ref'] ? XLSX.utils.decode_range(ws['!ref']) : { s: { r: 0, c: 0 }, e: { r: 0, c: 0 } };
    sheetC0 = rng.s.c; sheetEndC = rng.e.c;
    const all = XLSX.utils.sheet_to_json(ws, { header: 1, defval: '', raw: false, blankrows: true });
    raw = []; rawSrc = [];
    all.forEach((r, k) => { if (r.some(c => String(c).trim() !== '')) { raw.push(r); rawSrc.push(rng.s.r + k); } });
    fileName = f.name;
    fileHandle = handle || null;
    fileKind = fileHandle ? (isCsv ? 'csv' : 'xlsx') : '';
    $('paste').value = '';
    $('hasHeader').checked = true;
    afterLoad();
    foldInput(true);
    return true;
  } catch (err) { showWarn('파일을 읽지 못했습니다: ' + err.message); return false; }
}

function downloadBlob(blob, name) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

if (!('showOpenFilePicker' in window)) { $('openFS').hidden = true; }
$('openFS').addEventListener('click', async () => {
  try {
    const [h] = await window.showOpenFilePicker({
      multiple: false, mode: 'readwrite',
      types: [{ description: '엑셀·CSV', accept: {
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
        'application/vnd.ms-excel': ['.xls'],
        'text/csv': ['.csv'] } }]
    });
    const f = await h.getFile();
    let handle = h;
    if (/\.xls$/i.test(f.name)) {
      handle = null; toast('.xls 는 원본에 직접 쓸 수 없어 앱 폴더의 CSV로 자동 저장합니다.');
    } else {
      let perm = await h.queryPermission({ mode: 'readwrite' });
      if (perm !== 'granted') perm = await h.requestPermission({ mode: 'readwrite' });
      if (perm !== 'granted') { handle = null; toast('원본 파일 쓰기 권한이 없어 앱 폴더의 CSV로 자동 저장합니다.'); }
    }
    const okLoad = await loadFile(f, handle);
    if (okLoad && handle) { downloadBlob(f, '백업_' + f.name); toast('원본 사본을 다운로드 폴더에 백업_' + f.name + ' 로 저장했습니다.'); }
  } catch (e) { if (e.name !== 'AbortError') showWarn('파일을 열지 못했습니다: ' + e.message); }
});

function foldInput(fold) { $('inBox').hidden = fold; $('foldIn').textContent = fold ? '펼치기' : '접기'; }
$('foldIn').addEventListener('click', () => foldInput(!$('inBox').hidden));

function updateSaveLabel() {
  const s = $('saveState'); s.classList.remove('err');
  if (!$('auto').checked) { s.textContent = '자동 저장 꺼짐'; return; }
  s.textContent = fileHandle ? `대상: 원본 파일 ${fileName} — 변환 결과가 생기면 바로 반영`
                             : '대상: 앱 폴더의 geocode_autosave.csv (붙여넣기·.xls·일반 열기)';
}
function setSaveState(msg, err) {
  const s = $('saveState'); s.classList.toggle('err', !!err);
  const t = new Date(), hms = [t.getHours(), t.getMinutes(), t.getSeconds()].map(n => String(n).padStart(2, '0')).join(':');
  s.textContent = `${msg} · ${hms}`;
}
$('auto').addEventListener('change', () => { updateSaveLabel(); if ($('auto').checked) scheduleSave(); });

function scheduleSave() { clearTimeout(saveTimer); saveTimer = setTimeout(doSave, 1200); }

/* 원본 시트에 변환 결과만 덧붙인다: 주소(수정된 칸)와 새 열 5개만 쓰고 나머지 셀은 건드리지 않는다 */
function syncSheet() {
  const ws = wb.Sheets[sheetName], enc = XLSX.utils.encode_cell;
  const c = colIdx(), hh = $('hasHeader').checked, off = hh ? 1 : 0, nc = sheetEndC + 1;
  if (hh) ['위도', '경도', '변환상태', '변환주소', '원본주소'].forEach((l, k) => { ws[enc({ r: rawSrc[0], c: nc + k })] = { t: 's', v: l }; });
  rows.forEach((r, i) => {
    const sr = rawSrc[i + off]; if (sr === undefined) return;
    const x = results[i], done = x && !x.pending;
    if (isEdited(i)) ws[enc({ r: sr, c: sheetC0 + c })] = { t: 's', v: r[c] };
    const put = (k, cell) => { const a = enc({ r: sr, c: nc + k }); if (cell === null) delete ws[a]; else ws[a] = cell; };
    put(0, done && x.ok ? { t: 'n', v: x.lat } : null);
    put(1, done && x.ok ? { t: 'n', v: x.lon } : null);
    put(2, done ? { t: 's', v: statusText(i) } : null);
    put(3, done && x.ok && x.refined ? { t: 's', v: x.refined } : null);
    put(4, isEdited(i) ? { t: 's', v: String(orig[i] ?? '') } : null);
  });
  const rng = XLSX.utils.decode_range(ws['!ref']);
  rng.e.c = Math.max(rng.e.c, nc + 4);
  ws['!ref'] = XLSX.utils.encode_range(rng);
}

async function doSave() {
  clearTimeout(saveTimer);
  if (!$('auto').checked || !rows.length || !results.some(r => r && !r.pending)) return;   // 변환 결과가 생기기 전에는 원본을 건드리지 않는다
  if (saving) { saveAgain = true; return; }
  saving = true; lastSaveAt = Date.now();
  try {
    let target;
    if (fileHandle) {
      let data;
      if (fileKind === 'xlsx') { syncSheet(); data = XLSX.write(wb, { bookType: 'xlsx', type: 'array' }); }
      else data = '﻿' + XLSX.utils.sheet_to_csv(XLSX.utils.aoa_to_sheet(buildAoa(true)));
      const w = await fileHandle.createWritable(); await w.write(data); await w.close();
      target = '원본 ' + fileName;
    } else {
      const res = await fetch('/api/autosave', { method: 'POST', headers: { 'X-Token': TOKEN, 'Content-Type': 'application/json' }, body: JSON.stringify({ rows: buildAoa(true) }) });
      const d = await res.json(); if (!d.ok) throw new Error(d.error || '저장 실패');
      target = d.file;
    }
    dirty = false; setSaveState('저장됨 (' + target + ')', false);
  } catch (e) {
    setSaveState('저장 실패: ' + e.message + (fileHandle ? ' (엑셀에서 열려 있으면 닫고 다시 시도하세요)' : ''), true);
  } finally {
    saving = false;
    if (saveAgain) { saveAgain = false; doSave(); }
  }
}

/* ---------- 필터 · 다음 실패 ---------- */
function setFilter(f) {
  const t = $('tbl'); t.classList.remove('f-fail', 'f-ok', 'f-edit');
  if (f !== 'all') t.classList.add('f-' + f);
  document.querySelectorAll('#flt button').forEach(b => b.classList.toggle('on', b.dataset.f === f));
}
$('flt').addEventListener('click', e => { const b = e.target.closest('button[data-f]'); if (b) setFilter(b.dataset.f); });

$('nextFail').addEventListener('click', () => {
  const n = rows.length; if (!n) return;
  for (let k = 1; k <= n; k++) {
    const i = (selected + k + n) % n, r = results[i];
    if (r && !r.ok && !r.pending) {
      selectRow(i, true);
      document.querySelector(`#r${i} input.addr`)?.focus({ preventScroll: true });
      return;
    }
  }
  toast('실패한 행이 없습니다.');
});

/* ---------- 좌우 폭 조절 ---------- */
let curSide = 0;
function setSide(px, persist) {
  px = Math.max(380, Math.min(px, window.innerWidth - 320)); curSide = px;
  document.documentElement.style.setProperty('--side', px + 'px');
  map.invalidateSize();
  if (persist) { try { localStorage.setItem('geoSideW', String(Math.round(px))); } catch (e) {} }
}
try { const v = +localStorage.getItem('geoSideW'); if (v > 0) setSide(v, false); } catch (e) {}
$('split').addEventListener('pointerdown', e => {
  e.preventDefault();
  const sp = $('split');
  sp.classList.add('drag'); document.body.style.cursor = 'col-resize'; document.body.style.userSelect = 'none';
  sp.setPointerCapture?.(e.pointerId);
  const move = ev => setSide(ev.clientX, false);
  const up = () => {
    sp.classList.remove('drag'); document.body.style.cursor = ''; document.body.style.userSelect = '';
    window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up);
    setSide(curSide, true);
  };
  window.addEventListener('pointermove', move); window.addEventListener('pointerup', up);
});
$('split').addEventListener('dblclick', () => {
  document.documentElement.style.removeProperty('--side'); map.invalidateSize();
  try { localStorage.removeItem('geoSideW'); } catch (e) {}
});
$('split').addEventListener('keydown', e => {
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
  e.preventDefault();
  const cur = curSide || $('split').getBoundingClientRect().left;
  setSide(cur + (e.key === 'ArrowRight' ? 40 : -40), true);
});

/* ---------- 종료 ---------- */
$('quit').addEventListener('click', async () => {
  if ($('auto').checked) { try { await doSave(); } catch (e) {} }
  const msg = dirty ? '저장하지 않은 수정 내용이 있습니다.\n그래도 프로그램을 종료할까요?' : '프로그램을 종료할까요?';
  if (!confirm(msg)) return;
  try { await fetch('/api/shutdown', { method: 'POST', headers: { 'X-Token': TOKEN } }); } catch (e) {}
  $('bye').hidden = false;
});
</script>
</body>
</html>
'''

# ------------------------------------------------------------------ 실행


def main():
    global SERVER
    if not API_KEY:
        print("[경고] VWORLD_API_KEY 가 비어 있습니다. .env 파일에 인증키를 입력하세요. (화면은 열리지만 변환은 되지 않습니다)")
    try:
        SERVER = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as e:
        print(f"[오류] 포트 {PORT} 를 열 수 없습니다 ({e}). 이미 실행 중이면 종료 후 다시 실행하거나 .env 에 PORT=8001 처럼 다른 번호를 지정하세요.")
        sys.exit(1)
    url = f"http://127.0.0.1:{PORT}"
    print(f"실행 중: {url}   (종료: 화면의 [종료] 버튼 또는 Ctrl+C)")
    if KAKAO_KEY:
        print("카카오 검색: 사용")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        SERVER.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        SERVER.server_close()
    print("종료되었습니다.")


if __name__ == "__main__":
    main()
