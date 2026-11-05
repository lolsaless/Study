# -*- coding: utf-8 -*-
"""수집기 공통: 인증키 읽기, HTTP JSON 요청(재시도)"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
KEYS = BASE / "data" / "api_keys.env"


def read_key(name: str, cli: str | None = None) -> str:
    """--key 인자 → 환경변수 → data/api_keys.env 의 NAME=값 순서로 찾는다(저장소에 키를 올리지 말 것)"""
    if cli:
        return cli
    if os.environ.get(name):
        return os.environ[name]
    if KEYS.exists():
        for line in KEYS.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    sys.exit(f"인증키 {name} 가 없습니다. data/api_keys.env 에 {name}=키 한 줄을 넣으세요(양식: collectors/api_keys.env.example).")


def get_json(url: str, params: dict | None = None, retries: int = 4, timeout: int = 60):
    """(JSON 또는 None, 오류문)"""
    if params:
        # data.go.kr 인증키는 '디코딩' 키를 넣으면 여기서 한 번만 인코딩된다
        url = url + "?" + urllib.parse.urlencode(params, safe=":")
    err = ""
    for k in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "tms-analysis-3/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                txt = r.read().decode("utf-8", errors="replace")
            try:
                return json.loads(txt), ""
            except json.JSONDecodeError:
                return None, f"JSON 아님(인증키·파라미터 오류 가능): {txt[:300]}"
        except Exception as e:  # noqa: BLE001
            err = str(e)
            time.sleep(2 * (k + 1))
    return None, err


def items_of(js):
    """data.go.kr 표준 응답에서 item 목록 꺼내기(response/body/items/item 또는 getXxx/item 형태 모두)"""
    if not isinstance(js, dict):
        return [], "응답 없음"
    for root in [js.get("response"), *[v for v in js.values() if isinstance(v, dict)]]:
        if not isinstance(root, dict):
            continue
        head = root.get("header", {})
        code = str(head.get("resultCode", head.get("code", "00")))
        if code not in ("00", "0", "000"):
            return [], f"{code} {head.get('resultMsg', head.get('message', ''))}"
        body = root.get("body", root)
        it = body.get("items", body.get("item", []))
        if isinstance(it, dict):
            it = it.get("item", it)
        if isinstance(it, dict):
            it = [it]
        return (it or []), ""
    return [], "형식 모름"
