# -*- coding: utf-8 -*-
"""
TMS 부착 사업소 ↔ 하수도정보시스템 / 공공하수 / 공공폐수 매칭

입력 : 시트 4개가 든 엑셀 (TMS 부착 사업소, 하수도정보시스템, 공공하수, 공공폐수)
출력 : ① 원본 4개 시트 + 'TMS 시설정보'·'매칭 확인필요' 시트를 넣은 새 엑셀
       ② 연구 패키지용 site_facility.csv (DATA_SPEC C-3 형식, 공공하수만)

사용법
    python tms_facility_match.py 입력.xlsx [출력.xlsx]

매칭 순서
  1) 사업소명에서 시군(가평·남양주 …)과 핵심명(북면·1화도 …)을 분리
  2) 같은 시군 안에서 핵심명이 같은 시설을 찾음 (공백·'제'·'공공하수처리시설' 등 제거 후 비교)
     - 하수도정보시스템의 '○○ 증설' 행은 본 시설에 합산
  3) 이름이 다른 시설(가평항사=현리, 의정부민락2=낙양 …)은 MANUAL 표로 지정
     (주소를 대조해 확인한 결과)
  4) 소재지: 세 자료의 주소를 지번/도로명으로 나눠 읍면동·리, 도로명이 맞는지 대조
     - 두 자료 이상이 같은 값을 주면 그 값, 아니면 TMS → 하수도정보 → 공공하수 순
     - 엑셀이 날짜로 바꿔 손상된 TMS 주소(3/1/33 등)는 시설자료 주소로 대체
     - 옛 행정구역명(여주군, 교하읍, 모현면 …)과 행정동(죽전2동 → 죽전동)은 현행 법정명으로 고침
     - 자료끼리 다른 곳은 ADDR_FIX 표에서 근거와 함께 확정
  용량·공법: 하수도정보시스템(증설 합산) 우선, 없으면 공공하수 / 공공폐수는 공공폐수 자료
시설구분
  하수도정보시스템·공공하수에 있으면 '공공하수', 공공폐수에 있으면 '공공폐수', 나머지는 '사업장폐수'
  (예외: 사업소명이 '…하수'인데 경기도 자료에 없는 시설은 '공공하수'로 두고 비고에 표시)
"""
import re
import sys
from datetime import datetime, timedelta

import pandas as pd

# ----------------------------------------------------------------------------
# 0. 수동 지정 (자동 매칭이 안 되거나 틀리는 경우만)
#    값: dict(sewer=[하수도정보시스템 시설명...], pub=[공공하수 시설명...],
#              ww=[공공폐수 시설명...], note='...')
#    sewer/pub/ww 를 빈 리스트로 두면 '해당 자료에 없음'으로 고정
# ----------------------------------------------------------------------------
MANUAL = {
    # --- 이름이 다른 하수처리시설 (주소 대조로 확인) ---
    "가평항사하수": dict(pub=["현리공공하수처리시설"], note="공공하수 자료명 '현리'(상면 항사리 149)"),
    "가평하수": dict(pub=["가평공공하수처리시설"]),
    "구리1하수": dict(sewer=["구리"], pub=["구리공공하수처리시설"],
                  note="구리처리장 1단계 방류구. 용량·공법은 처리장 전체(1·2단계 합계)"),
    "구리2하수": dict(sewer=["구리"], pub=["구리공공하수처리시설"],
                  note="구리처리장 2단계 방류구. 용량·공법은 처리장 전체(1·2단계 합계)"),
    "오산1하수": dict(sewer=["오산"], pub=["오산시환경사업소"],
                  note="오산처리장 1처리장. 용량·공법은 처리장 전체(1·2처리장 합계)"),
    "오산2하수": dict(sewer=["오산"], pub=["오산시환경사업소"],
                  note="오산처리장 2처리장. 용량·공법은 처리장 전체(1·2처리장 합계)"),
    "안산하수1단계": dict(sewer=["안산"], pub=["안산공공하수처리시설"],
                    note="안산처리장 1처리장(Symbio). 용량은 처리장 전체(1·2처리장 합계)"),
    "안산하수2단계": dict(sewer=["안산"], pub=["안산공공하수처리시설"],
                    note="안산처리장 2처리장(BNR-C). TMS 소재지(성곡동 681-1)는 2처리장 부지. 용량은 처리장 전체"),
    "성남하수": dict(sewer=["성남 제1 제2"], pub=["성남수질복원센터 1처리장", "성남수질복원센터 2처리장"],
                 note="성남수질복원센터 1·2처리장 합계(245,000+215,000)"),
    "성남판교하수": dict(sewer=["판교수질복원센터"], pub=["판교수질복원센터"]),
    "수원서호천하수": dict(sewer=["서호생태 수자원센터"], pub=["서호생태수자원센터"]),
    "수원하수": dict(sewer=["수원"], pub=["수원환경사업소"], note="수원환경사업소 — 소재지는 화성시 송산동(태안로 263)"),
    "수원황구지천하수": dict(sewer=["황구지천"], pub=[]),
    "의정부민락2하수": dict(sewer=["낙양"], pub=["낙양물사랑공원"],
                     note="낙양물사랑공원(민락2지구, 용민로 205)"),
    "의정부하수": dict(sewer=["의정부"], pub=["의정부공공하수처리시설"]),
    "의왕왕송(부곡)하수": dict(sewer=["왕송"], pub=["왕송하수처리장"]),
    "안양하수": dict(sewer=["안양"], pub=["안양새물공원"]),
    "안양석수하수": dict(sewer=["석수"], pub=["석수공공하수처리시설"]),
    "군포대야하수": dict(sewer=["대야"], pub=["대야물말끔터"]),
    "군포부곡하수": dict(sewer=["부곡"], pub=["부곡공공하수처리시설"]),
    "시흥월곶하수": dict(sewer=["월곶에코피아"], pub=["월곶에코피아"]),
    "시흥장현하수": dict(sewer=["장현"], pub=["장현수질복원센터"]),
    "시흥시화하수": dict(sewer=["시화"], pub=["시화공공하수처리시설"]),
    "시흥목감하수": dict(sewer=["목감"], pub=["목감수질복원센터"]),
    "남양주1화도하수": dict(sewer=["제 1화도"], pub=["제1화도 공공하수처리시설"]),
    "남양주2화도하수": dict(sewer=["제 2화도"], pub=["제2화도"]),
    "남양주지금하수": dict(sewer=["지금"], pub=["지금푸른물센터"]),
    "남양주월산하수": dict(sewer=["월산"], pub=["월산푸른물센터"]),
    "남양주진건하수": dict(sewer=["진건"], pub=["진건환경사업소"]),
    "남양주진접하수": dict(sewer=["진접"], pub=["진접푸른물센터"]),
    "남양주별내하수": dict(sewer=["별내"], pub=["별내푸른물센터"]),
    "구리갈매하수": dict(sewer=["갈매수질복원센터"], pub=["구리갈매수질복원센터"]),
    "연천백학하수": dict(sewer=["백학물새롬센터"], pub=["백학공공하수처리시설"]),
    "연천하수": dict(sewer=["연천"], pub=["연천공공하수처리시설"]),
    "용인하수": dict(sewer=["용인레스피아"], pub=["용인레스피아"],
                 note="공공하수 자료의 용인레스피아 6,000㎥/일은 증설분으로 보임 — 용량은 하수도정보시스템(56,000) 사용"),
    "용인아곡하수": dict(sewer=["아곡"], pub=["아곡레스피아"]),
    "용인고매하수": dict(sewer=["고매"], pub=["고매레스피아"]),
    "용인구갈하수": dict(sewer=["구갈"], pub=["구갈레스피아"]),
    "용인기흥하수": dict(sewer=["기흥"], pub=["기흥레스피아"]),
    "용인모현하수": dict(sewer=["모현"], pub=["모현레스피아"]),
    "용인상현하수": dict(sewer=["상현"], pub=["상현레스피아"]),
    "용인서천하수": dict(sewer=["서천"], pub=["서천레스피아"]),
    "용인수지하수": dict(sewer=["수지"], pub=["수지레스피아"]),
    "용인영덕하수": dict(sewer=["영덕"], pub=["영덕레스피아"]),
    "용인천리하수": dict(sewer=["천리"], pub=["천리레스피아"]),
    "고양벽제하수": dict(sewer=["벽제"], pub=["벽제수질복원센터"]),
    "고양삼송하수": dict(sewer=["삼송"], pub=["삼송수질복원센터"]),
    "고양원능하수": dict(sewer=["원능"], pub=["원능수질복원센터"]),
    "고양일산하수": dict(sewer=["일산"], pub=["일산수질복원센터"]),
    "과천하수": dict(sewer=["과천"], pub=["과천시환경사업소"]),
    "여주하수": dict(sewer=["여주"], pub=["여주시환경사업소"]),
    "양평하수": dict(sewer=["양평"], pub=["양평군환경사업소"]),
    "양평양서하수": dict(sewer=["양서"], pub=["양서공공하수처리시설"]),
    "오산세마하수": dict(sewer=["세마"], pub=["세마하수처리장"]),
    "화성동탄2하수": dict(sewer=["동탄2"], pub=["동탄2공공하수처리시설"],
                    note="공공하수 자료에 같은 시설이 '화성동탄 수질복원센터'로 한 번 더 실려 있음(중복)"),
    "화성남양하수": dict(sewer=["남양", "남양2 증설"], pub=["남양하수처리장"]),
    "화성봉담하수": dict(sewer=["봉담", "봉담2 증설1", "봉담3"], pub=["봉담공공하수처리시설"],
                   note="하수도정보시스템 봉담·봉담2 증설1·봉담3(같은 부지 수영리) 합계"),
    "화성향남하수": dict(sewer=["향남"], pub=["향남하수처리장"]),
    "화성향남2하수": dict(sewer=["향남2"], pub=["향남2하수처리장"]),
    "화성조암하수": dict(sewer=["조암"], pub=["조암하수처리장"]),
    "화성정남하수": dict(sewer=["정남"], pub=["정남하수처리장"]),
    "화성양감하수": dict(sewer=["양감"], pub=["양감공공하수처리시설"]),
    "화성새미하수": dict(sewer=["새미"], pub=[]),
    "화성매송하수": dict(sewer=["매송"], pub=[]),
    "평택포승하수": dict(sewer=["포승"], pub=["포승공공하수처리장"]),
    "평택팽성하수": dict(sewer=["팽성"], pub=["팽성하수처리시설"]),
    "평택통복하수": dict(sewer=["통복"], pub=["통복공공하수"]),
    "평택이화하수": dict(sewer=["이화"], pub=["이화공공하수처리시설"]),
    "평택청북하수": dict(sewer=["청북"], pub=["청북공공하수처리시설"]),
    "평택고덕하수": dict(sewer=["고덕"], pub=[]),
    "이천장호원하수": dict(sewer=["장호원"], pub=["장호원하수처리장"]),
    "포천2하수": dict(sewer=["포천2공공하수처리시설"], pub=[]),
    "포천일이동하수": dict(sewer=["일이동"], pub=["일이동하수처리시설"]),
    "광주양벌하수": dict(sewer=["양벌"], pub=["양벌하수처리장"]),
    "광주삼리하수": dict(sewer=["삼리"], pub=["삼리하수처리장"]),
    "광주하수": dict(sewer=["광주"], pub=["광주공공하수처리시설"]),
    "안성불당하수": dict(sewer=["불당"], pub=["불당하수종말처리장"]),
    "안성진사하수": dict(sewer=["진사"], pub=["진사하수종말처리장"]),
    "양주신천하수": dict(sewer=["신천"], pub=["신천공공하수처리시설|양주"]),
    "가평신천하수": dict(sewer=["신천"], pub=["신천공공하수처리시설|가평"]),
    "이천단월하수": dict(sewer=["단월"], pub=["단월공공하수처리시설|이천"]),
    "양평단월하수": dict(sewer=["단월"], pub=["단월공공하수처리시설|양평"]),
    "고양난지하수": dict(sewer=[], pub=[], kind="공공하수",
                   note="서울시 난지물재생센터(서울 하수 처리, 소재지 고양시) — 경기도 자료에 없음. 시설용량 등 별도 확인 필요"),

    # --- 공공폐수 ---
    "안성1폐수": dict(ww=["안성 제1 공공폐수처리시설"]),
    "안성2폐수": dict(ww=["안성 제 2 공공폐수처리시설"]),
    "연천청산폐수": dict(ww=["청산대전 공공폐수처리시설"]),
    "김포양촌폐수": dict(ww=["양촌 공공폐수처리시설"]),
    "파주LCD폐수": dict(ww=["LCD 공공폐수처리시설"]),
    "파주문산폐수": dict(ww=["문산 공공폐수처리시설"],
                   note="공공폐수 자료 위치는 '파주읍 돈유1로 13', TMS는 '문산읍 향양리 702(돈유1로 13)' — 도로명 일치"),
    # 공공폐수 목록에 없는 '…폐수' 사업소 (규칙대로 사업장폐수, 비고 표시)
    "김포양촌2폐수": dict(ww=[], note="명칭상 산업단지 폐수처리시설이나 공공폐수 자료에 없음(양촌 공공폐수와 별도) — 시설구분 확인 필요"),
    "용인테크노밸리폐수": dict(ww=[], note="명칭상 산업단지 폐수처리시설이나 공공폐수 자료에 없음 — 시설구분 확인 필요"),
    "평택고덕폐수": dict(ww=[], note="명칭상 산업단지 폐수처리시설이나 공공폐수 자료에 없음 — 시설구분 확인 필요"),
    "화성바이오밸리폐수": dict(ww=[], note="명칭상 산업단지 폐수처리시설이나 공공폐수 자료에 없음 — 시설구분 확인 필요"),
    "화성전곡해양폐수": dict(ww=[], note="명칭상 산업단지 폐수처리시설이나 공공폐수 자료에 없음 — 시설구분 확인 필요"),

    # --- 사업장폐수 중 메모가 필요한 곳 ---
    "용인시환경자원화시설": dict(sewer=[], pub=[], note="용인시 음식물·분뇨 등 처리시설(고매레스피아와 같은 부지) — 공공하수 목록에 없어 사업장폐수로 분류"),
}

# 소재지 수동 지정: 자료끼리 다를 때 근거를 확인해 고른 값
#   jibun/road 를 지정하면 그 값을 쓰고, '' 로 두면 비움. note는 비고에 추가
ADDR_FIX = {
    "평택고덕하수": dict(jibun="경기도 평택시 고덕동 2686",
                   note="TMS '고덕면 궁리 289-10'은 고덕국제신도시 조성 전 지번 — 하수도정보시스템의 현행 지번 사용"),
    "용인백암하수": dict(road="", note="공공하수 자료 도로명 '근장로 35 176'은 형식 오류로 제외"),
    "반월정수(안산)": dict(road="경기도 안산시 상록구 정재초교길 61", jibun="",
                     note="TMS 소재지 손상 — 안산시 상하수도사업소 정수장 현황의 반월정수장(K-water) 주소로 보완"),
    "성남정수(성남)": dict(note="TMS 소재지 손상 — K-water 성남정수장/성남시 복정정수장 중 어느 곳인지 확인 후 입력 필요"),
    "남양주진접하수": dict(jibun="경기도 남양주시 진접읍 연평리 39", note="TMS(연평리 39·해밀예당1로 30-31)와 시설자료(금곡리 1085)가 다름 — TMS 주소 유지, 확인필요"),
    "연천임진하수": dict(note="TMS '미산면 우정리 313' / 하수도정보 '미산면 동이리 313' — 리 이름 다름, 확인필요"),
    "여주금사하수": dict(jibun="경기도 여주시 금사면 외평리 491-4",
                   note="TMS '금사리 568'과 달리 하수도정보·공공하수 모두 '외평리 491-4' — 시설자료 주소 사용"),
}

# 사업소명 → 정수장 등 메모 (사업장폐수 분류는 유지)
WATER_PLANT_PAT = re.compile(r"정수")

# 행정구역 명칭 변경(지번주소에만 적용). 확실한 것만 넣음.
ADMIN_RENAME = [
    (r"여주군", "여주시"),
    (r"여주시 여주읍 점봉리", "여주시 점봉동"),
    (r"여주시 여주읍 ", "여주시 "),
    (r"여주시 능서면", "여주시 세종대왕면"),
    (r"여주시 가남면", "여주시 가남읍"),
    (r"광주시 중부면", "광주시 남한산성면"),
    (r"파주시 교하읍 문발동", "파주시 문발동"),
    (r"파주시 교하읍 와동리", "파주시 와동동"),
    (r"파주시 교하읍 ", "파주시 "),
    (r"처인구 모현면", "처인구 모현읍"),
    (r"용인시 모현면", "용인시 처인구 모현읍"),
    (r"용인시 이동면", "용인시 처인구 이동읍"),
    (r"처인구 이동면", "처인구 이동읍"),
    (r"처인구 남사면", "처인구 남사읍"),
    (r"평택시 청북면", "평택시 청북읍"),
    (r"^경기 ", "경기도 "),
    # 행정동·행정리 → 법정동·리 (예: 죽전2동 → 죽전동, 덕소7리 → 덕소리)
    (r"(\s[가-힣]+?)\d+(동|리)(?=\s)", r"\1\2"),
]

# ----------------------------------------------------------------------------
# 1. 공통 유틸
# ----------------------------------------------------------------------------
FAC_WORDS = ["공공하수처리시설", "공공하수처리장", "하수종말처리장", "하수처리시설", "하수처리장",
             "공공폐수처리시설", "공공하수", "소규모"]


def clean(s):
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()


def norm_name(s):
    s = clean(s)
    for w in FAC_WORDS:
        s = s.replace(w, "")
    s = s.replace(" ", "")
    s = re.sub(r"^제(?=\d)", "", s)
    return s


def is_garbled(addr):
    """엑셀이 날짜로 바꿔버린 주소(예: 3/1/33) 또는 빈 값"""
    a = clean(addr)
    return a == "" or bool(re.fullmatch(r"[\d/.\- :]+", a))


def excel_date(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, (int, float)) and 20000 < v < 60000:
        return (datetime(1899, 12, 30) + timedelta(days=int(v))).strftime("%Y-%m-%d")
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    s = clean(v)
    return "" if s in ("-", "") else s + " (원자료 표기)"


# ----------------------------------------------------------------------------
# 2. 주소 분해·비교
# ----------------------------------------------------------------------------
ROAD_RE = re.compile(r"([가-힣A-Za-z0-9]+(?:로|길)(?:\s?\d+(?:번)?(?:길|가길))?)\s*(\d+(?:-\d+)?)")
JIBUN_RE = re.compile(r"([가-힣0-9]+(?:동|리|가))\s*(산\s?)?(\d+(?:-\d+)?)")
AREA_RE = re.compile(r"([가-힣]+(?:읍|면))")


def pre_norm(a):
    """띄어쓰기·표기 차이 정리"""
    a = clean(a).replace("ㅡ", "-").replace("–", "-")
    a = re.sub(r"\s*-\s*", "-", a)
    a = re.sub(r"(\S+(?:로|길))\s+(\d+(?:번)?(?:길|가길))", r"\1\2", a)   # 판교로 228번길 → 판교로228번길
    a = re.sub(r"제\s+(\d)", r"제\1", a)                                   # 제 2공단 → 제2공단
    a = re.sub(r"(\d+공단)\s+(\d+길)", r"\1\2", a)
    a = re.sub(r"([가-힣](?:동|리))(\d)", r"\1 \2", a)                      # 구갈동33 → 구갈동 33
    a = re.sub(r"(\d)번지", r"\1", a)
    a = re.sub(r"([가-힣0-9](?:로|길))(\d+)(?!\d*(?:번길|가길|길))", r"\1 \2", a)  # 내향로360 → 내향로 360
    a = re.sub(r"\(\s+", "(", a)
    a = re.sub(r"\s+\)", ")", a)
    return a


ADMIN_TOK = re.compile(r"^(경기도|경기|[가-힣]+(?:시|군|구|읍|면))$")


def admin_prefix(p):
    toks = p.split()
    out = []
    for t in toks:
        if ADMIN_TOK.match(t):
            out.append(t)
        else:
            break
    return " ".join(out)


def trim_tail(p, kind):
    """번지·건물번호 뒤에 붙은 시설명 등을 잘라냄"""
    rx = ROAD_RE if kind == "road" else JIBUN_RE
    m = None
    for m in rx.finditer(p):
        pass
    return p[: m.end()] if m else p


def split_addr(a):
    """주소 1개 → (본문, 괄호안) 으로 나눈 뒤 각각 지번/도로명 판별"""
    a = pre_norm(a)
    parts = [a]
    if "(" in a:
        main = a[: a.index("(")].strip()
        inner = a[a.index("(") + 1:].rstrip(")").strip()
        pre = admin_prefix(main)
        if inner and not inner.startswith("경기") and pre:
            # 괄호 안이 '리/동'으로 시작하면 읍면까지, 도로명이면 시군구(+읍면)까지 붙임
            inner = pre + " " + inner
        parts = [main, inner]
    out = {"road": "", "jibun": ""}
    for p in parts:
        if not p:
            continue
        if ROAD_RE.search(p):
            out["road"] = out["road"] or trim_tail(p, "road")
        elif JIBUN_RE.search(p):
            out["jibun"] = out["jibun"] or trim_tail(p, "jibun")
    return out


def road_key(a):
    """도로명+건물번호 키 (예: '폭포로562', '달전로31번길48')"""
    m = ROAD_RE.search(clean(a))
    if not m:
        return ""
    return (m.group(1) + m.group(2)).replace(" ", "")


def road_name(a):
    m = ROAD_RE.search(clean(a))
    return m.group(1).replace(" ", "") if m else ""


def jibun_key(a):
    """법정동·리 이름 (예: '이곡리', '달전리')과 번지"""
    m = JIBUN_RE.search(clean(a))
    if not m:
        return "", ""
    return m.group(1), (("산" if m.group(2) else "") + m.group(3))


def apply_rename(a):
    for pat, rep in ADMIN_RENAME:
        a = re.sub(pat, rep, a)
    return a


def ensure_prefix(a, sigun_full):
    """'북면 이곡리 586-4' → '경기도 가평군 북면 이곡리 586-4'"""
    a = clean(a)
    if not a:
        return ""
    a = re.sub(r"^경기\s", "경기도 ", a)
    a = re.sub(r"^경기도(?=\S)", "경기도 ", a)
    if a.startswith("경기도"):
        # '경기도 부천시오정구' 처럼 붙어 있는 경우
        a = re.sub(r"(시|군)(?=[가-힣]+구\s)", r"\1 ", a, count=1)
        return a
    short = sigun_full[:-1]
    if a.startswith(sigun_full):
        return "경기도 " + a
    if a.startswith(short + "시") or a.startswith(short + "군"):
        return "경기도 " + a
    if a.startswith(short + " "):
        a = a[len(short) + 1:]
    return f"경기도 {sigun_full} {a}"


# ----------------------------------------------------------------------------
# 3. 자료 읽기
# ----------------------------------------------------------------------------
def load(path):
    xl = pd.read_excel(path, sheet_name=None, dtype=object)
    tms = xl["TMS 부착 사업소"].rename(columns=lambda c: clean(c))
    sew = xl["하수도정보시스템"].rename(columns=lambda c: clean(c))
    pub = xl["공공하수"].rename(columns=lambda c: clean(c))
    ww = xl["공공폐수"].rename(columns=lambda c: clean(c))
    return tms, sew, pub, ww


def build_tables(sew, pub, ww):
    sigun_full = sorted({clean(x) for x in sew["구분"]}, key=len, reverse=True)
    short2full = {f[:-1]: f for f in sigun_full}

    sew = sew.copy()
    sew["시군"] = sew["구분"].map(clean)
    sew["key"] = sew["하수처리시설명"].map(norm_name)
    sew["base"] = sew["하수처리시설명"].map(
        lambda s: norm_name(re.sub(r"\d*\s*증설\d*", "", clean(s))) if "증설" in clean(s) and "(" not in clean(s) else None)

    def pub_sigun(loc):
        loc = clean(loc)
        m = re.match(r"(?:경기도\s*)?([가-힣]+?)(?:시|군)?[\s(]", loc)
        if not m:
            return ""
        s = m.group(1)
        if s == "양서":  # 원자료 오기 '양서(양수리 814-1)'
            return "양평군"
        return short2full.get(s, "")

    pub = pub.copy()
    pub["시군"] = pub["위치"].map(pub_sigun)
    pub["key"] = pub["시설명"].map(norm_name)
    pub["위치_전체"] = [ensure_prefix(re.sub(r"^[가-힣]+?\((.*)\)?$", r"\1", clean(l)).rstrip(")"), s) if s else clean(l)
                      for l, s in zip(pub["위치"], pub["시군"])]

    ww = ww.copy()
    ww["시군"] = ww["위치"].map(lambda l: next((f for f in sigun_full if f in clean(l)), ""))
    ww["key"] = ww["시설명"].map(lambda s: norm_name(s).replace("공공폐수처리시설", ""))
    return sigun_full, short2full, sew, pub, ww


# ----------------------------------------------------------------------------
# 4. 사업소 1개 매칭
# ----------------------------------------------------------------------------
def parse_tms_name(name, short2full):
    """'가평북면하수' → ('가평군', '북면', '하수')"""
    n = clean(name)
    kind = "하수" if re.search(r"하수(\d단계)?$", n) else ("폐수" if n.endswith("폐수") else "")
    if not kind or re.search(r"\([가-힣]+\)$", n):
        return "", "", ""
    for short in sorted(short2full, key=len, reverse=True):
        if n.startswith(short):
            core = re.sub(r"(하수|폐수)(\d단계)?$", "", n[len(short):])
            return short2full[short], norm_name(core) or short, kind
    return "", "", ""


def pick_rows(df, names, namecol, sigun):
    rows = []
    for nm in names:
        nm_, _, sg = nm.partition("|")
        cand = df[df[namecol].map(clean) == clean(nm_)]
        if sg:
            cand = cand[cand["시군"].str.startswith(sg)]
        elif sigun and "시군" in cand and (cand["시군"] == sigun).any():
            cand = cand[cand["시군"] == sigun]
        if len(cand) == 0:
            raise KeyError(f"수동 지정한 시설명을 찾지 못함: {nm}")
        rows.append(cand.iloc[0])
    return rows


def match_one(name, short2full, sew, pub, ww):
    sigun, core, kind = parse_tms_name(name, short2full)
    man = MANUAL.get(name, {})
    res = dict(sigun=sigun, sew=[], pub=[], ww=[], how=[], note=man.get("note", ""), kind=man.get("kind"))

    # 하수도정보시스템
    if "sewer" in man:
        res["sew"] = pick_rows(sew, man["sewer"], "하수처리시설명", sigun)
        if man["sewer"]:
            res["how"].append("하수도정보:수동")
    elif kind == "하수":
        m = sew[(sew["시군"] == sigun) & (sew["key"] == core)]
        if len(m):
            res["sew"] = [m.iloc[0]] + [r for _, r in sew[(sew["시군"] == sigun) & (sew["base"] == core)].iterrows()]
            res["how"].append("하수도정보:자동")
    # 공공하수
    if "pub" in man:
        res["pub"] = pick_rows(pub, man["pub"], "시설명", sigun)
        if man["pub"]:
            res["how"].append("공공하수:수동")
    elif kind == "하수":
        m = pub[(pub["시군"] == sigun) & (pub["key"] == core)]
        if len(m) == 1:
            res["pub"] = [m.iloc[0]]
            res["how"].append("공공하수:자동")
    # 공공폐수
    if "ww" in man:
        res["ww"] = pick_rows(ww, man["ww"], "시설명", sigun)
        if man["ww"]:
            res["how"].append("공공폐수:수동")
    elif kind == "폐수":
        m = ww[(ww["시군"] == sigun) & (ww["key"] == core)]
        if len(m) == 1:
            res["ww"] = [m.iloc[0]]
            res["how"].append("공공폐수:자동")
    return res


# ----------------------------------------------------------------------------
# 5. 소재지 교차검증
# ----------------------------------------------------------------------------
def resolve_address(tms_addr, cands, sigun):
    """
    tms_addr : TMS 원 소재지
    cands    : [(출처, 전체주소), ...]  (하수도정보·공공하수·공공폐수)
    반환     : 지번주소, 도로명주소, 검증결과, 사용출처
    """
    srcs = []
    if not is_garbled(tms_addr):
        srcs.append(("TMS", ensure_prefix(tms_addr, sigun) if sigun else clean(tms_addr)))
    srcs += [(s, a) for s, a in cands if clean(a)]

    parsed = [(s, split_addr(a)) for s, a in srcs]
    roads = [(s, p["road"]) for s, p in parsed if p["road"]]
    jibuns = [(s, p["jibun"]) for s, p in parsed if p["jibun"]]

    # 도로명: 여러 출처가 같은 도로명+번호면 그 값, 아니면 TMS → 하수도정보 → 공공 순
    rk = {}
    for s, a in roads:
        rk.setdefault(road_key(a), []).append((s, a))
    road = ""
    if rk:
        best = max(rk.values(), key=len)
        road = best[0][1] if len(best) > 1 else roads[0][1]
    # 지번: 같은 원칙
    jk = {}
    for s, a in jibuns:
        jk.setdefault(jibun_key(a), []).append((s, a))
    jibun = ""
    if jk:
        best = max(jk.values(), key=len)
        jibun = best[0][1] if len(best) > 1 else jibuns[0][1]

    # 검증: 출처끼리 동·리 또는 도로명이 맞는지
    def stem(d):
        return re.sub(r"\d*(동|리|가)$", "", d)

    dongs = {s: stem(jibun_key(a)[0]) for s, a in jibuns}
    nums = {s: jibun_key(a)[1].split("-")[0] for s, a in jibuns}
    rnames = {s: road_name(a) for s, a in roads}
    n_src = len(srcs)
    tms_ok = "TMS" in [s for s, _ in srcs]
    agree, disagree = [], []
    others = [s for s, _ in srcs if s != "TMS"]
    if tms_ok and others:
        for o in others:
            same_d = dongs.get("TMS") and dongs.get(o) and dongs["TMS"] == dongs[o]
            same_d = same_d or (nums.get("TMS") and nums.get("TMS") == nums.get(o)
                                and (dongs.get("TMS") in dongs.get(o, "") or dongs.get(o, "-") in dongs.get("TMS", "")))
            same_r = rnames.get("TMS") and rnames.get(o) and rnames["TMS"] == rnames[o]
            if same_d or same_r:
                agree.append(o)
            elif (dongs.get("TMS") and dongs.get(o)) or (rnames.get("TMS") and rnames.get(o)):
                disagree.append(o)
    if n_src == 0:
        status = "주소 없음"
    elif not tms_ok:
        status = "TMS 소재지 손상 → 시설자료 주소로 대체"
    elif not others:
        status = "TMS 단독(대조자료 없음)"
    elif agree and not disagree:
        status = "일치(" + "·".join(agree) + ")"
    elif agree and disagree:
        status = "부분일치(" + "·".join(agree) + " 일치 / " + "·".join(disagree) + " 다름)"
    elif disagree:
        status = "불일치(" + "·".join(disagree) + ") — 확인필요"
    else:
        status = "비교불가(주소 형식 다름)"

    # 지번·도로명 중 하나가 없으면 다른 출처로 보완했는지 기록
    used = sorted({s for s, a in roads if a == road} | {s for s, a in jibuns if a == jibun})
    jibun = apply_rename(ensure_prefix(jibun, sigun)) if jibun and sigun else apply_rename(jibun)
    road = ensure_prefix(road, sigun) if road and sigun else road
    road = apply_rename(road)
    return jibun, road, status, "·".join(used)


def first_full(jibun, road):
    return road or jibun


# ----------------------------------------------------------------------------
# 6. 실행
# ----------------------------------------------------------------------------
def fmt_num(v):
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return None


def run(inp, outp):
    tms, sew, pub, ww = load(inp)
    sigun_full, short2full, sew, pub, ww = build_tables(sew, pub, ww)

    recs = []
    for _, t in tms.iterrows():
        name = clean(t["사업소"])
        raw_addr = clean(t["소재지"])
        r = match_one(name, short2full, sew, pub, ww)

        # 사업장폐수는 시군을 소재지에서 추정
        sigun = r["sigun"] or next((f for f in sigun_full if f in raw_addr), "")
        if not sigun:
            m = re.search(r"\(([가-힣]+)\)$", name)
            if m and m.group(1) in short2full:
                sigun = short2full[m.group(1)]

        # 시설구분
        if r["kind"]:
            kind = r["kind"]
        elif r["sew"] or r["pub"]:
            kind = "공공하수"
        elif r["ww"]:
            kind = "공공폐수"
        else:
            kind = "사업장폐수"

        # 용량·공법: 하수 = 하수도정보시스템(증설 합산) 우선, 없으면 공공하수 / 폐수 = 공공폐수
        cap_sew = sum(fmt_num(x["시설용량(㎥/일)"]) or 0 for x in r["sew"]) if r["sew"] else None
        cap_pub = sum(fmt_num(x["시설용량(㎥/d)"]) or 0 for x in r["pub"]) if r["pub"] else None
        cap_ww = sum(fmt_num(x["시설용량(㎥/d)"]) or 0 for x in r["ww"]) if r["ww"] else None
        proc_sew = " / ".join(dict.fromkeys(clean(x["처리공법"]) for x in r["sew"] if clean(x["처리공법"])))
        proc_pub = " / ".join(dict.fromkeys(clean(x["처리방법"]) for x in r["pub"] if clean(x["처리방법"])))
        proc_ww = " / ".join(dict.fromkeys(clean(x["처리방법"]) for x in r["ww"] if clean(x["처리방법"])))

        if kind == "공공폐수":
            cap, cap_src, proc, proc_src = cap_ww, "공공폐수", proc_ww, "공공폐수"
        elif cap_sew:
            cap, cap_src = cap_sew, "하수도정보시스템"
            proc, proc_src = (proc_sew, "하수도정보시스템") if proc_sew else (proc_pub, "공공하수")
        elif cap_pub:
            cap, cap_src, proc, proc_src = cap_pub, "공공하수", proc_pub, "공공하수"
        else:
            cap, cap_src, proc, proc_src = None, "", proc_sew or proc_pub, ""

        cap_flag = ""
        if cap_sew and cap_pub and abs(cap_sew - cap_pub) / max(cap_sew, cap_pub) > 0.05:
            cap_flag = f"용량 차이: 하수도정보 {cap_sew:,} / 공공하수 {cap_pub:,}"

        start = ""
        for x in r["pub"] + r["ww"]:
            start = excel_date(x.get("가동개시일"))
            if start:
                break

        # 주소 후보
        cands = [("하수도정보", ensure_prefix(x["시설위치"], sigun) if sigun else clean(x["시설위치"])) for x in r["sew"][:1]]
        cands += [("공공하수", x["위치_전체"]) for x in r["pub"][:1]]
        cands += [("공공폐수", clean(x["위치"])) for x in r["ww"][:1]]
        jibun, road, status, used = resolve_address(raw_addr, cands, sigun)
        fix = ADDR_FIX.get(name, {})
        if "jibun" in fix:
            jibun = fix["jibun"]
        if "road" in fix:
            road = fix["road"]
        if fix:
            status = status.replace(" — 확인필요", "") + (" → 수동확정" if ("jibun" in fix or "road" in fix) else " — 확인필요")

        note = [r["note"]] if r["note"] else []
        if fix.get("note"):
            note.append(fix["note"])
        if kind == "사업장폐수" and WATER_PLANT_PAT.search(name) and not r["note"]:
            note.append("정수장(정수처리시설) — 규칙에 따라 사업장폐수로 분류")
        if is_garbled(raw_addr):
            note.append(f"TMS 소재지가 '{raw_addr}'로 손상됨(엑셀 날짜 변환)")
        if cap_flag:
            note.append(cap_flag)
        if raw_addr and ("여주군" in raw_addr or "중부면" in raw_addr or "교하읍" in raw_addr
                         or "모현면" in raw_addr or "이동면" in raw_addr or "청북면" in raw_addr):
            note.append("옛 행정구역명 → 현행 명칭으로 수정")

        recs.append({
            "사업소": name,
            "시설구분": kind,
            "시군": sigun,
            "하수도정보시스템 시설명": " + ".join(clean(x["하수처리시설명"]) for x in r["sew"]),
            "공공하수·공공폐수 시설명": " + ".join([clean(x["시설명"]) for x in r["pub"]] + [clean(x["시설명"]) for x in r["ww"]]),
            "소재지(정리)": road or jibun or ("" if is_garbled(raw_addr) else apply_rename(ensure_prefix(pre_norm(raw_addr), sigun) if sigun else raw_addr)),
            "지번주소": jibun,
            "도로명주소": road,
            "소재지 검증": status,
            "시설용량(㎥/일)": cap,
            "처리공법": proc,
            "가동개시일": start,
            "용량 출처": cap_src,
            "공법 출처": proc_src,
            "참고: 공공하수 용량": cap_pub if kind == "공공하수" and cap_sew and cap_pub else None,
            "참고: 공공하수 처리방법": proc_pub if kind == "공공하수" and proc_sew else "",
            "TMS 원 소재지": raw_addr,
            "매칭 방법": ", ".join(r["how"]) or ("해당없음" if kind == "사업장폐수" else ""),
            "비고": " / ".join(note),
        })

    out = pd.DataFrame(recs)
    need = out[(out["소재지 검증"].str.contains("확인필요|주소 없음"))
               | out["비고"].str.contains("확인필요|확인 필요|손상|경기도 자료에 없음")]
    write_excel(inp, outp, out, need)

    # 연구용 data/site_facility.csv (DATA_SPEC C-3 형식, 공공하수만)
    sf = out[out["시설구분"] == "공공하수"].copy()
    sf = pd.DataFrame({
        "site": sf["사업소"], "sigun": sf["시군"],
        "capacity_m3d": pd.to_numeric(sf["시설용량(㎥/일)"]).round().astype("Int64"), "process": sf["처리공법"],
        "start_date": sf["가동개시일"].where(~sf["가동개시일"].str.contains("원자료", na=False), ""),
        "expansion_date": "", "service_pop": "",
        "source": sf["용량 출처"].replace({"하수도정보시스템": "경기도 하수도정보시스템", "공공하수": "경기도 공공하수처리시설 현황"}),
    })
    csv_path = re.sub(r"\.xlsx$", "", outp) + "_site_facility.csv"
    sf.to_csv(csv_path, index=False, encoding="utf-8-sig")
    return out, need


def write_excel(inp, outp, out, need):
    from openpyxl import load_workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = load_workbook(inp)
    for nm in ("TMS 시설정보", "매칭 확인필요"):
        if nm in wb.sheetnames:
            del wb[nm]
    widths = {"사업소": 22, "시설구분": 10, "시군": 9, "하수도정보시스템 시설명": 18, "공공하수·공공폐수 시설명": 24,
              "소재지(정리)": 42, "지번주소": 38, "도로명주소": 38, "소재지 검증": 30, "시설용량(㎥/일)": 12,
              "처리공법": 30, "가동개시일": 12, "용량 출처": 14, "공법 출처": 14, "참고: 공공하수 용량": 12,
              "참고: 공공하수 처리방법": 30, "TMS 원 소재지": 40, "매칭 방법": 24, "비고": 60}
    head_fill = PatternFill("solid", fgColor="1F4E78")
    ref_fill = PatternFill("solid", fgColor="7F7F7F")
    kind_fill = {"공공하수": "DDEBF7", "공공폐수": "FCE4D6", "사업장폐수": "EDEDED"}
    warn_fill = PatternFill("solid", fgColor="FFF2CC")

    for title, df in (("TMS 시설정보", out), ("매칭 확인필요", need)):
        ws = wb.create_sheet(title)
        cols = list(df.columns)
        ws.append(cols)
        for row in df.itertuples(index=False):
            ws.append([None if (isinstance(v, float) and pd.isna(v)) else v for v in row])
        for j, c in enumerate(cols, 1):
            cell = ws.cell(1, j)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = ref_fill if j > cols.index("가동개시일") + 1 else head_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            ws.column_dimensions[get_column_letter(j)].width = widths.get(c, 14)
        ki = cols.index("시설구분") + 1
        vi = cols.index("소재지 검증") + 1
        ci = cols.index("시설용량(㎥/일)") + 1
        for i in range(2, ws.max_row + 1):
            k = ws.cell(i, ki).value
            if k in kind_fill:
                ws.cell(i, ki).fill = PatternFill("solid", fgColor=kind_fill[k])
            v = str(ws.cell(i, vi).value or "")
            if any(w in v for w in ("불일치", "부분일치", "손상", "비교불가")):
                ws.cell(i, vi).fill = warn_fill
            ws.cell(i, ci).number_format = "#,##0"
        ws.freeze_panes = "B2"
        ws.auto_filter.ref = ws.dimensions
        ws.row_dimensions[1].height = 30
    # 순서: 원 TMS 시트 → TMS 시설정보 → 매칭 확인필요 → 나머지 원자료
    order = ["TMS 부착 사업소", "TMS 시설정보", "매칭 확인필요"]
    wb._sheets = [wb[n] for n in order if n in wb.sheetnames] + \
                 [ws for ws in wb.worksheets if ws.title not in order]
    for ws in wb.worksheets:
        ws.sheet_view.tabSelected = False
    wb.active = 1
    wb["TMS 시설정보"].sheet_view.tabSelected = True
    wb.save(outp)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    inp = sys.argv[1]
    outp = sys.argv[2] if len(sys.argv) > 2 else re.sub(r"\.xlsx$", "", inp) + "_시설정보.xlsx"
    out, need = run(inp, outp)
    print(out["시설구분"].value_counts().to_string())
    print(f"확인필요 {len(need)}건 → {outp}")
