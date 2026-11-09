# -*- coding: utf-8 -*-
"""
tms_analysis_3 공통 설정 (경로·변수·기준값·임계값)
- 여기만 고치면 모든 스크립트에 반영된다.
- 새 자료를 추가할 때 고칠 곳: 대부분 '없음'. 표준 양식(data/standard/)으로 바꿔 넣기만 하면 된다(작업안내서.md 3장).
"""
from pathlib import Path

# ── 경로 ────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"              # 원자료(받은 그대로, 수정 금지)
INBOX_DIR = DATA_DIR / "inbox"          # 새로 받은 자료를 일단 넣는 곳 → 매핑으로 표준화
STD_DIR = DATA_DIR / "standard"         # 표준 양식 자료(분석 스크립트는 여기만 읽는다)
META_DIR = DATA_DIR / "meta"            # 측정소 정보·연결표(사람이 고치는 표)
WORK_DIR = BASE_DIR / "work"            # 캐시(지워도 다시 만들어짐, git 제외)
RESULTS_DIR = BASE_DIR / "results"      # 분석 결과
MAPPINGS_DIR = BASE_DIR / "ingest" / "mappings"
KEYS_FILE = DATA_DIR / "api_keys.env"   # API 인증키(git 제외). 양식: collectors/api_keys.env.example

NIER_XLSX_DIR = RAW_DIR / "nier_auto_xlsx"          # 물환경정보시스템 '시간자료' xlsx (연도/권역/파일)
NIER_DAILY_V2_DIR = RAW_DIR / "nier_auto_daily_v2"  # 기존 merge_water_day.py 산출물(대체 입력)

# 다른 프로젝트 자료(선택) — 수질TMS(방류수) 정제자료. 없으면 42·43·45번은 '자료 대기'
TMS_CLEAN_PKL = BASE_DIR.parent / "tms_analysis_2" / "work" / "tms_clean.pkl"
TMS_SITE_COORDS = BASE_DIR.parent / "tms_analysis_2" / "data" / "site_coords.csv"     # site, lat, lon (지도·유역 배정)
TMS_SITE_REGION = BASE_DIR.parent / "tms_analysis_2" / "data" / "site_region.csv"     # site, region, std_* (방류수 기준 지역)
SITE_FACILITY_CSV = META_DIR / "site_facility.csv"   # (선택) site, capacity_m3d, process, start_date … — 45번 원인 분석

# GIS(선택) — 측정소별 상류 유역 구역 배정(tools/assign_upstream.py)
GIS_DIR = RAW_DIR / "gis"                             # 표준유역·중권역 경계(.geojson 또는 .shp)
STATION_CATCHMENT_CSV = META_DIR / "station_catchment.csv"   # station, catchment_codes(; 구분) — 측정소 상류 구역 목록

# ── 측정 항목 ────────────────────────────────────────────
CORE_VARS = ["WT", "pH", "EC", "DO", "Turb", "TOC", "TN", "TP", "Chl_a"]
EXTRA_VARS = ["NH3_N", "NO3_N", "PO4_P"]               # 일부 측정소만
VAR_INFO = {   # 코드: (한글명, 단위)
    "WT": ("수온", "℃"), "pH": ("수소이온농도", "-"), "EC": ("전기전도도", "μS/cm"),
    "DO": ("용존산소", "mg/L"), "Turb": ("탁도", "NTU"), "TOC": ("총유기탄소", "mg/L"),
    "TN": ("총질소", "mg/L"), "TP": ("총인", "mg/L"), "Chl_a": ("클로로필-a", "mg/㎥"),
    "NH3_N": ("암모니아성질소", "mg/L"), "NO3_N": ("질산성질소", "mg/L"), "PO4_P": ("인산염인", "mg/L"),
    "DO_sat": ("용존산소 포화도", "%"),
}
LOG_VARS = ["EC", "Turb", "TOC", "TN", "TP", "Chl_a", "NH3_N", "NO3_N", "PO4_P"]   # 로그 척도가 자연스러운 항목
BASINS = ["한강", "낙동강", "금강", "영산강"]
STATION_ALIAS = {"동북호": "동복호"}     # 파일명 오기 등 측정소 이름 통일

# ── 자료 사용 규칙 ──────────────────────────────────────
MIN_HOURS = 18          # 일평균을 쓰려면 그날 유효 시간 수가 이 이상
MIN_DAYS = 300          # 측정소×항목 시계열 분석 최소 유효일수
FLATLINE_MIN_RUN = 72   # 시간자료에서 같은 값이 n시간 이상 연속 → 고정값(센서 정지) 의심
FLATLINE_MIN_DAYS = 5   # 일자료에서 일평균이 n일 이상 같으면 고정값 의심
ROLL_WIN = 31           # 계절 성분 제거용 이동 중앙값 창(일)
SPIKE_Z = 6.0           # 품질 진단 급변 기준(강건 z)
ANOMALY_Z = 5.0         # 이상 사건 기준(계절 제거 편차의 강건 z)
MD_MAX_ROWS = 40        # summary.md 표 최대 행 수

# ── 하천·호소 생활환경기준(환경정책기본법 시행령 별표1) ─────────
# ※ 반드시 현행 법령으로 다시 확인하고 쓰세요. 등급: Ia, Ib, II, III, IV, V, VI
GRADES = ["Ia", "Ib", "II", "III", "IV", "V", "VI"]
RIVER_STD = {   # 각 등급의 상한(이하이면 그 등급). DO는 하한(이상)
    "TOC": [2, 3, 4, 5, 6, 8],
    "TP": [0.02, 0.04, 0.1, 0.2, 0.3, 0.5],
    "DO": [7.5, 5.0, 5.0, 5.0, 2.0, 2.0],
}
LAKE_STD = {
    "TOC": [2, 3, 4, 5, 6, 8],
    "TP": [0.01, 0.02, 0.03, 0.05, 0.10, 0.15],
    "TN": [0.2, 0.3, 0.4, 0.6, 1.0, 1.5],
    "Chl_a": [5, 9, 14, 20, 35, 70],
    "DO": [7.5, 5.0, 5.0, 5.0, 2.0, 2.0],
}
TARGET_GRADE = "II"     # 목표기준(측정소별 목표는 data/meta/stations.csv 의 target_grade 로 덮어씀)

# ── 조류·저산소 임계값 ──────────────────────────────────
BLOOM_CHLA = 25.0       # 조류 증식일 기준 Chl-a(mg/㎥). 수질예보·조류경보 기준과 대조해 조정
HYPOXIA_DO = 5.0        # 저산소 기준(mg/L) — 일최솟값 기준
SUPERSAT_PCT = 120.0    # 과포화(광합성 과다) 기준(%)

# ── 기상·유량 연계 ──────────────────────────────────────
WET_DAY_MM = 1.0        # 강수일
EVENT_MM = 20.0         # 강우 사건(당일 또는 2일 누적)
DRY_PRIOR_DAYS = 3      # 건기일 = 당일 포함 직전 n일 강수 < WET_DAY_MM
API_K = 0.9             # 선행강우지수 감쇠계수

# ── 부하 수지·강우 초과 부하(43·44) ─────────────────────
FLOW_ZONES = [(0, 0.30, "저유량"), (0.30, 0.90, "중간"), (0.90, 1.01, "고유량")]   # 하천 유량 백분위 구간
MIN_SITE_REPORT = 0.8   # 상류 사업장 중 이 비율 이상이 보고한 날만 TMS 부하 합계를 쓴다
EFFLUENT_DOMINATED = 0.5   # 저유량 시 방류수량/하천유량 ≥ 이 값 → '처리수 지배 하천'

# ── 방류수 수질기준(공공하수처리시설 500 m³/일 이상, mg/L) — 45번 ──────────
# ※ 반드시 현행 「하수도법 시행규칙」 별표로 확인. 지역은 TMS_SITE_REGION(site,region)로 지정, 없으면 DEFAULT_REGION
DISCHARGE_STANDARDS = {
    "I":   {"TOC": 15, "SS": 10, "TN": 20, "TP": 0.2},
    "II":  {"TOC": 15, "SS": 10, "TN": 20, "TP": 0.3},
    "III": {"TOC": 25, "SS": 10, "TN": 20, "TP": 0.5},
    "IV":  {"TOC": 25, "SS": 10, "TN": 20, "TP": 2.0},
}
DEFAULT_REGION = "I"
FACILITY_TYPES = ["하수"]          # 45번 평가 대상 TMS 유형
# 평가 영역 가중치(합 1). 바꾸면 점수·순위가 바뀌므로 정책 협의 후 확정
FACILITY_SCORE_WEIGHTS = {"기준 여유": 0.35, "안정성": 0.25, "강우 대응": 0.20, "자료 관리": 0.20}

# ── 공휴일(요일 분석에서 제외) ────────────────────────────
HOLIDAYS = [
    "2024-01-01", "2024-02-09", "2024-02-10", "2024-02-11", "2024-02-12", "2024-03-01",
    "2024-04-10", "2024-05-05", "2024-05-06", "2024-05-15", "2024-06-06", "2024-08-15",
    "2024-09-16", "2024-09-17", "2024-09-18", "2024-10-01", "2024-10-03", "2024-10-09", "2024-12-25",
    "2025-01-01", "2025-01-27", "2025-01-28", "2025-01-29", "2025-01-30", "2025-03-01", "2025-03-03",
    "2025-05-05", "2025-05-06", "2025-06-03", "2025-06-06", "2025-08-15",
    "2025-10-03", "2025-10-05", "2025-10-06", "2025-10-07", "2025-10-08", "2025-10-09", "2025-12-25",
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-03-01", "2026-03-02",
    "2026-05-05", "2026-05-24", "2026-05-25", "2026-06-03", "2026-06-06", "2026-08-15", "2026-08-17",
    "2026-09-24", "2026-09-25", "2026-09-26", "2026-10-03", "2026-10-05", "2026-10-09", "2026-12-25",
]

# ── 기타 ─────────────────────────────────────────────────
RANDOM_STATE = 42
FIG_DPI = 130
N_BOOT = 1000           # 부트스트랩 반복 수
