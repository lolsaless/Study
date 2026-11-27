# Study — 원자료 수집 지침 (통합본)

> 2026-11-26 통합. 이 파일 하나가 `Study/` 의 지침이다. 예전 문서(통합수집_안내, 수질자료수집_개발지침, 강수량·수위 개발지침, 수계지도_부품지도, 프로젝트_지침 사본)는 모두 여기로 합쳤다(옛 판: `Data/_backup/지침통합전_20261126.zip`).
> API 요청·응답 형식은 **`Data/API_참고.md`**, 지점·항목 코드표는 `Data/수질측정망/site_code/수질측정망_지점코드.md`.
> 분석·연구 규칙은 `연구사업/README.md` 와 프로젝트 문서 `claude/TMS_연구_진행현황.md` 를 따른다.

**Claude 읽는 순서**: 이 파일에서 필요한 절만 → (요청 코드를 짤 때만) `API_참고.md` 해당 절 → 고칠 코드. `raw_data/`·`tms_crawling/data/`(파일 수천 개)·`total/`·지도 원본(shp·geojson 수백 MB)은 재귀 나열하거나 통째로 읽지 않는다.

---

## 1. 폴더 지도 (`Study/Data/`, 맥미니 `~/Documents/GitHub/Study`, GitHub `Study` main)

| 폴더·파일 | 자료 | 수집 코드 | 인증키(따로 돌릴 때) |
|---|---|---|---|
| `통합수집.py` | 아래 주제 코드를 연구 범위로 돌려 `total/` 에 모으고 연구사업에 덧붙임(2절) | — | `통합수집.env` |
| `total/` | 한탄강 연구 범위 원자료 모음(2024~). 코드가 만든다, 손대지 않음 | 통합수집.py | — |
| `수질측정망/` | 물환경 수질측정망(월 1~4회 채수), 한강 648지점 | `물환경_수질측정망.py` | `물환경.env` |
| `하천수질자동측정망/` | 국가 수질자동측정망. `2024_2025/`(xlsx 시간자료 → 일별 통합), `2026/`(API 시간자료), `data/`(결합본) | `2024_2025/Code/merge_water_*.py`, `2026/fetch_auto_water_quality.py`, `수질자동측정망_결합.py` | `2026/.env` (DATA_GO_KR_API_KEY) |
| `하수폐수자동측정망/` | 방류수 TMS(soosiro) 크롤링 `tms_crawling/`. 지난 경기도 분석 `tms_analysis_1~3/` 은 11-26 `연구사업/_archive/tms_analysis_경기도전체_20261126.zip` 으로 옮김 | `tms_crawling/soosiro_tms_4.py` | 필요 없음(크롬) |
| `강수량/` | 기상청 API허브 ASOS 일자료 | `기상청_ASOS_일자료.py` | `기상청.env` (KMA_AUTH_KEY) |
| `수위/` | 한강홍수통제소 수위·유량·우량 일자료 | `홍수통제소_수위유량.py` | `홍수통제소.env` (HRFCO_KEY) |
| `Location_위도경도/` | VWorld 주소 → 위경도(지오코딩) | `vworld_geocoder.py` | `.env` (VWORLD_API_KEY) |
| `지도/` | 실폭하천 수계지도(6절) | `extract_river_map.py` | 필요 없음 |

**주제 폴더 공통 틀**: `수집코드.py` / `*.env` / `site_code/`(지점 코드표) / `raw_data/`(받은 그대로, 연도·지점 단위) / `data/`(결합본 + `columns.csv`) / `_backup/`(고치기 전 사본). 새 주제도 이 틀을 따른다.

---

## 2. 통합 수집 (`통합수집.py`)

```
각 주제 폴더 수집 코드 ──(범위·저장 위치만 바꿔 실행)──▶ Study/Data/total/   (연구 범위, 2024~, 원본 형태)
                                                              │ 덧붙이기(기존 행 그대로, 지점별 마지막 날 다음만)
                                                              ▼
                       연구사업/data_tms/      수질자동측정망_data.csv, 하수폐수측정망_data.csv
                       연구사업/data_weather/  weather_daily.csv, flow_daily.csv  (merge_from_study.py --study total)
```

- 주제 폴더 자료는 건드리지 않는다. 통합 실행으로 받은 것은 `total/` 에만 쌓인다(주제 코드를 따로 돌리면 예전처럼 주제 폴더에 받는다).
- 연구사업 파일은 열·형식이 그대로다. 분석 기간은 연구사업 `config.END`(지금 2026-06-30)가 정하므로 END 를 바꾸기 전까지 분석 결과는 같다.
- total 만으로 연구사업 파일을 **새로** 만들면 지금과 다르다(ASOS 기온 출처가 달라 ±0.1~1.1℃, 연구사업에만 있는 범위 밖 지점). 그래서 기본은 덧붙이기.

### 2-1. 범위 (`통합수집.py` 맨 위 '★ 연구 범위')

| 자료 | 범위 | 새로 받는 기간 |
|---|---|---|
| 하천 수질자동측정망 | 포천 S01017, 한탄강 S01009, 신천 S01013, 미산 S01016 | 2026-01-01 ~ 오늘(확정 전이라 매번 다시) |
| 방류수 TMS | 이름에 양주·동두천·포천·연천(남양주 제외), 2026Q3 목록 39곳 | `--tms` 로 준 분기 |
| 기상청 ASOS | 철원 95, 동두천 98, 파주 99 | 올해(지난 연도 파일은 있으면 건너뜀) |
| 홍수통제소 | 수위·유량 11곳(분석 핵심 6곳 + 분석 h00 이 쓰는 파주 5곳) + BBOX 안, 우량계 BBOX 안 | 관측소별 마지막 날 60일 전부터 |

### 2-2. 인증키
- 통합수집은 **`Data/통합수집.env` 하나만** 읽는다: `DATA_GO_KR_API_KEY`(공공데이터포털) · `KMA_AUTH_KEY`(기상청 API허브) · `HRFCO_KEY`(홍수통제소). TMS 크롤링은 키 불필요.
- 새 PC: `python 통합수집.py --init-keys`(주제 폴더 `.env` 에서 빠진 키만 복사, 화면에 키 안 씀). 주제 폴더 `.env` 가 없으면(윈도우 git 사본 등) `통합수집.env.example` 을 복사해 이름을 바꾸고 키를 적는다.
- 키가 없으면 그 자료만 건너뛴다. 키를 새로 받으면 `통합수집.env` 와 해당 주제 폴더 `.env` 를 함께 고친다.
- 통합수집 실행 중 화면 출력의 키는 `***` 로 가린다. 주제 코드를 직접 돌리면 기상청 코드는 오류 문장에 키를 찍을 수 있다.

### 2-3. 명령

| 명령 | 하는 일 |
|---|---|
| `--check` | 받지 않고 total/·연구사업 파일이 어디까지 있는지 표 |
| `--test` | 하천·기상·수위 API 연결만 확인(파일 안 바꿈) |
| (없음) | 하천·기상·수위 수집 → total/ 결합 → 연구사업 덧붙이기 |
| `--tms 2026Q4` | TMS 그 분기만 크롤링 → total/ → 연구사업. `--tms-refresh`(잠정치 p → 확정치 다시), `--tms-include-open`(안 끝난 분기), `--tms-show`(창 보이기) |
| `--only river weather level` | 일부만 |
| `--merge-only` / `--no-research` | 받지 않고 결합·반영만 / 연구사업은 안 건드림 |
| `--research-fill-gaps` | 연구사업 파일 기간 안 빈 (지점, 날짜)도 total 값으로 채움(기존 값 유지, **결과가 바뀔 수 있음**) |
| `--research-overwrite` | 겹치는 날 값을 total 에 맞추고 빈 날도 채움(하천 2026 확정치·TMS 확정치 반영용, **결과가 바뀔 수 있음**) |
| `--init-total` / `--init-keys` | total/ 에 빠진 시드 파일 채우기 / 인증키 모으기 |

결과: `Data/통합수집_요약.md`(마지막 실행), `total/수집이력.md`(받거나 합친 실행 누적). `--check`·`--init-keys` 는 기록을 남기지 않는다. 바뀐 연구사업 파일의 이전 판은 각 폴더 `_backup/<날짜시각>/`.

### 2-4. total/ 구조

| 폴더 | 원본(받은 그대로) | 결합본 |
|---|---|---|
| `total/하천수질자동측정망/` | `raw_data/한강_일별_2024_2025.csv`, `raw_data/by_site/<코드>_<이름>_<월>.csv` | `data/data_수질자동측정망.csv`, `data/수질자동측정망_2026.csv` |
| `total/하수폐수자동측정망/` | `raw/<분기>/<사업장>.csv`(원표 문자열 그대로), `site_list_*.csv`, `confirmed_empty.csv` | `tms_all_raw.csv`, `tms_all_clean.csv` |
| `total/강수량/` | `raw_data/기상청_ASOS/<연도>.csv` | `data/기상청_ASOS_일자료.csv` 등 |
| `total/수위/` | `raw_data/홍수통제소/<waterlevel·rainfall>/<코드>.csv` | `data/홍수통제소_수위유량_일자료.csv` 등 |

### 2-5. 연구사업 반영 규칙
- 하천: 측정소별 마지막 날 다음 행만. TMS: (사업장, 방류구)별 마지막 날 다음 행만, 잠정치 표시 p 는 떼고, 같은 날 중복 행은 하나만(원표에 양주송추하수 2025-08-20·21 두 번).
- 기상·유량: `연구사업/data_weather/merge_from_study.py --apply --study total`. 기존 지점만, 마지막 날 다음부터. ASOS `RN_DAY` -9 → 0, 단 `RN_60M_MAX`·`RN_10M_MAX` > 0 이면 결측.
- 연구사업 파일의 범위 밖 자료(경기도 다른 사업장 등)는 그대로 남는다.
- 빈 날 경고: total 에 있는데 연구사업 기간 안에 없는 (지점, 날짜)는 `기존 기간 안 빈 날 N행 (안 붙임)` 으로 알린다 → 채울지는 `--research-fill-gaps`.
- iCloud 충돌 사본(`이름 2.csv`)은 결합에서 빼고 경고한다.
- 자료를 붙인 뒤 분석은 **`python run.py` 전체**(일부만 돌리면 옛 정제 자료를 읽어 `[이력] !!` 경고).

### 2-6. 확인한 것 / 못 한 것 (11-26)
- 확인(Claude 복사본): total 시드 ↔ 연구사업 대조 — 하천 4곳 3,227행 값 같음, TMS 39곳 37,400행 문자열까지 같음, 유량·우량 같음. 지운 뒤 반영하면 그대로 다시 붙고 02_정제 8개 파일이 바이트 단위로 같음. `--research-fill-gaps` 로 채운 값이 원래와 같음.
- 확인: 맥미니에서 `--init-total` 실행(23 MB), 주제 폴더·연구사업 파일 안 바뀜.
- 미검증: 실제 API 호출과 크롤링(Claude 환경은 외부 접속 차단). 처음에는 `--test`, 크롤링은 `--tms 2026Q3 --tms-show --no-research`.
- 파주 유량 5곳(1023667·1023670·1023671·1023677·1023680)은 total 에 아직 없음 → 첫 실제 수집 때 2024년부터 받음(연구사업에는 2026-07 이후만 붙음).

---

## 3. 주제별 수집 코드

### 3-1. 수질측정망 — `수질측정망/물환경_수질측정망.py`
- 대상: 물환경 수질측정망 대권역 한강 648지점(`getWaterMeasuringList`). 설정(맨 위): `START_YEAR`, `END_YEAR`(None=올해), `MONTHS`, `BASIN`, `SITE_TYPES`, `CODE_FILE`, `REFRESH_DONE_YEARS`.
- 실행: `python 물환경_수질측정망.py` → `raw_data/<연도>.csv` → **raw_data 전체**를 합쳐 `data/all_data.csv`·`columns.csv`·`sites_hangang.csv`. `--merge-only` = 결합만.
- 결합 규칙: `YYYY.csv`·`YYYY_partial.csv` 만, 완성본이 있으면 partial 버림, 항목 열 합집합, 열 순서 = 지점·시점 → `item*`(가나다) → 나머지, 중복 제거, 지점·검사일 정렬.
- 현황(11-17 맥미니): 2024 14,871 / 2025 13,463 / 2026 10,130행(~09-30) → 38,464행, 647지점(1곳 자료 없음). 요청 = 648 ÷ 10 = 연도당 65번(하루 한도 10,000번).
- 코드표: `site_code/물환경_수질측정망_지점코드_전체.csv`(2,218개), `수질자동측정망_측정소코드_전체.csv`(71개).

### 3-2. 하천 수질자동측정망 — `하천수질자동측정망/`
- 2024~25: 내려받은 xlsx 시간자료를 `2024_2025/Code/merge_water_xlsx.py`·`merge_water_day.py` 로 일별 통합(`Data/데이터_설명.md`, `merge_report.txt`).
- 2026: `2026/fetch_auto_water_quality.py` — `getRealTimeWaterQualityList`, 한강 S01001~S01025(23개소), 수온·pH·EC·DO·TOC·Chl-a·TN·TP·탁도. `raw_data/by_site/<코드>_<이름>_<YYYYMM>.csv`. 11-09 사용자 실행으로 2026-01~08 받음(API 가 일자료로 줌). `--end`, `--refresh`. **2026-11-27 수정**: API 가 요청 시작일(startDate …000000)의 자료를 주지 않아 매달 1일이 빠졌음(2026-01~09 모든 달·지점) → 하루 앞부터 요청하고 그 달로 다시 거름. 이미 받은 자료의 1일은 `python 통합수집.py --research-fill-gaps` 로 채움.
- 결합: `수질자동측정망_결합.py` → `data/data_수질자동측정망.csv`.

### 3-3. 방류수 TMS 크롤러 — `하수폐수자동측정망/tms_crawling/soosiro_tms_4.py`
- soosiro 사업장별 일 배출량(Selenium, 크롬만 있으면 됨, `pip install selenium pandas lxml`). 장애 자동복구·이어받기, 저장은 옆 `data/`.
- 11-26 추가 옵션: `--site-keys`·`--exclude-keys`·`--refresh`(없으면 예전과 같음, 원본 `_backup/`). 진단 `--diagnose`, 시험 `--years 2025 --quarters 1 --limit 3 --show`.
- `soosiro_tms_1~3.py`, `soosiro_tms_failed_*.py` 는 이전 판.

### 3-4. 강수량 — `강수량/기상청_ASOS_일자료.py`
- API허브 `kma_sfcdd3.php` 56개 열. 한 달 1번, 전국 한꺼번에(`stn=0`). 지난 연도는 파일 있으면 건너뜀, 올해는 매번. 실패 달이 있으면 `YYYY_partial.csv`.
- 설정: `START_DATE="2024-01-01"`, `END_DATE=None`(어제), `STATIONS=[]`(전국, 일부는 `[95,98,99]`), `REFRESH_DONE_YEARS`, `RAIN_NEG_AS_ZERO=True`.
- 실행: `--test`(최근 한 주 응답 앞부분) / (없음) / `--merge-only`.
- 결과: `data/기상청_ASOS_일자료.csv`(date, stn, stn_name + 원래 56열, 값 그대로), `data/기상청_ASOS_weather_daily.csv`(stn, stn_name, date, rain_mm, source, ta_mean, ta_min, ta_max — 연구사업 weather_daily 와 같은 열; 기온 -50 이하 → 빈칸, RN_DAY 음수 → 0 또는 빈칸), `data/기상청_ASOS_columns.csv`, `site_code/기상청_ASOS_지점.csv`.
- 주의: `RAIN_NEG_AS_ZERO=True` 라 실제 결측 -9 도 0 이 된다(충주 2025-07-17 55.9 mm 사례). 연구사업은 merge_from_study 가 원값에서 다시 계산(2-5절).

### 3-5. 수위·유량·우량 — `수위/홍수통제소_수위유량.py`
- `waterlevel`·`rainfall` 의 `list/1D` + `info.json`. 관측소마다 `CHUNK_DAYS`(31)씩, 관측소별 파일에 이어 붙임(같은 날은 새 값), 최근 `REFRESH_DAYS`(60)일 다시 받음(실시간 자료 보정).
- 설정: `START_DATE`/`END_DATE`, `GET_WATERLEVEL`/`GET_RAINFALL`, `WL_CODES`, `RF_CODES`, `BBOX=(37.80, 38.32, 126.85, 127.48)`.
- 실행: `--test` / `--list`(제원 + BBOX 안 목록) / (없음) / `--merge-only`.
- 결과: `data/홍수통제소_수위유량_일자료.csv`(obscd, obs_name, date, wl_m, flow_cms, source — 연구사업 flow_daily 와 같은 열), `data/홍수통제소_우량_일자료.csv`(stn="HR"+코드, …, rain_mm), `data/홍수통제소_대상관측소.csv`, `site_code/홍수통제소_*관측소.csv`(위경도 도-분-초 → 십진수, 원값 raw_lat·raw_lon).

| 코드 | 관측소 | 연구에서 쓰임 |
|---|---|---|
| 1022648 | 포천시(은현교) | 포천 측정망 유량 |
| 1022670 | 연천군(신천교) | 신천 측정망 유량 |
| 1022680 | 연천군(사랑교) | 한탄강 = 사랑교 − 신천교 |
| 1022662 | 연천군(차탄교) | 미산 = 임진교 + 사랑교 + 차탄교 |
| 1021680 | 연천군(임진교) | 〃 |
| 1022666 | 고탄교 | 유량 전 기간 0 → 분석에 안 씀 |

- 이 API 는 **실시간(확정 전) 자료**. 논문용 확정값은 WAMIS·수문조사연보와 대조.

### 3-6. 위경도 — `Location_위도경도/vworld_geocoder.py`
- 브라우저 화면 지오코더(VWorld, 선택 카카오). 주소 보정 재조회, 시·군 불일치 '확인필요'. `--selftest`(네트워크 없이 규칙 점검). 결과 좌표는 연구사업 `data_tms/*location*.csv` 에 반영됨(사용자 직접 확인, 고칠 필요 없음).

### 3-7. 첫 실제 실행 후 확인할 것(미검증)
- [ ] 기상청 `--test`: 설명 줄 형식, 값 구분, EUC-KR, TM 이 `YYYYMMDD` 인지, 비 안 온 날이 0.0 인지 -9.0 인지(→ `RAIN_NEG_AS_ZERO` 확정), 지점 좌표 채워졌는지, 기온 결측 코드
- [ ] 홍수통제소 `--test`: 최상위 키 `content`, 열 이름(`wlobscd·ymd·wl·fw` / `rfobscd·rf`), 날짜 형식 `%Y%m%d`, `--list` 에 비룡대교 등 포함, 31일 초과 요청 가능 여부, 유량 0 만 있는 관측소
- [ ] VWorld 수질측정망 지점 레이어 ID(`LT_P_WEISSITEMA` 추정)

---

## 4. 코드 작성 원칙 (모든 수집 코드 공통)

1. **설정은 코드 맨 위 상수**(기간 `START_*`·`END_*=None`, 대상, 파일명). 사용자는 거기만 고친다.
2. **경로는 코드 폴더 기준**: `BASE_DIR = Path(__file__).resolve().parent` 아래 `RAW_DIR`·`DATA_DIR`·`SITE_CODE_DIR`. 셸 명령 대신 Python, `pathlib` 만.
3. **인증키는 `.env` 에만.** 코드·문서·결과·화면에 쓰지 않는다. 변수 이름 후보 여러 개 → 하나뿐이면 그 값. 포털 인코딩 키는 `unquote()`. 홍수통제소는 키가 주소 경로에 들어가므로 오류 문구에서 가린다.
4. **한글 파일·폴더 이름은 NFC 로 비교해 실제 이름을 찾는다.** 맥(iCloud)은 NFD 로 저장(한글 이름 157개 중 155개) → 윈도우·리눅스에서 NFC 경로로 바로 열면 못 찾는다.
5. **지점 목록은 `site_code/` CSV 에서 읽는다**(utf-8-sig → cp949 순). 필요한 열이 없으면 알리고 멈춘다. 개수가 적으면 코드 안 사전도 됨.
6. **응답 처리**: 공공데이터포털은 XML + ElementTree, 결과코드 `00` 확인, `03`/0건 = 자료 없음(정상), 키 오류는 즉시 중단.
7. **재시도·속도**: 실패 3~4회 재시도(대기 늘려 가며), 요청 사이 0.3초, 묶어 요청(`ptNoList` 10개), 실행 전 예상 요청 수 출력.
8. **이어 받기**: 단위(지점×월, 연도)별로 `raw_data/` 에 저장, 받은 것은 건너뜀. 공개 중인 최근 기간(자동측정망 약 3개월, 올해)은 매번 다시. 일부 실패는 `_partial`.
9. **원값 보존**: `-999`(정량한계 미만)·0·이상치는 고치지 않는다. `n/a`·빈칸만 결측. 바꾼 값은 별도 파일에만, 규칙은 `columns.csv` 에.
10. **저장**: CSV `utf-8-sig`. 엑셀이 필요하면 xlsx 에 「자료」「현황」「열설명」 시트. 열 이름은 API 원래 이름 + 설명표.
11. **결합은 `raw_data/` 전체**를 읽는다(이번 실행분만 X). `--merge-only` 옵션을 둔다.
12. **실행 안내**: 첫머리 docstring 에 폴더·패키지·명령. 진행은 `[연도] 묶음 n/N: 건수`, 끝에 행·지점·기간 요약.
13. **환경**: 맥미니(Apple Silicon)·윈도우 노트북 둘 다에서 동작(인텔 맥은 기준 아님). `requests pandas`(+`openpyxl`) 중심. 설정 상수를 맨 위에 둘 때 `from __future__ import annotations` 는 쓰지 않는다. 행정망 PC 는 외부 API 가 막힐 수 있어 인터넷 PC 에서 수집.
14. **고치기 전 보관**: 크게 고칠 때 `_backup/<이름>_<날짜>_before.py`.

## 5. 시험·보고

- 사용자가 "직접 테스트하지 말라"고 하면 API 를 부르지 않고 `requests.Session.get` 을 가짜 응답으로 바꿔 끝까지 돌린 뒤 그렇게 했다고 말한다.
- 폴더가 연결된 대화에서는 사용자 폴더 밖 복사본에서 시험하고, 사용자 폴더에서는 API 를 부르지 않는 작업(파일 이동, `--merge-only`)만 한다.
- 명세와 실제가 다를 수 있는 부분(날짜 형식, 레이어 ID, JSON 구조)은 "첫 실행 후 확인할 점"으로 적는다. 코드표에서 확인한 사실(예: 한강 자동측정망 S01008·S01024 결번)은 코드 주석에 남긴다.

## 6. 수계지도 — `지도/extract_river_map.py`

- 입력: 국토지리정보원 연속수치지형도 `N3A_E0032111`(1:5,000 실폭하천 면, `.shp/.shx/.dbf/.prj` 한 폴더, Korea 2000 = EPSG:5179). 속성 `UFID`·`SCLS`·`FMTA`. 면만으로는 상·하류 연결·흐름 방향·실제 방류구를 판정할 수 없다.
- 지점: 기본은 `연구사업/analysis_hantan_river/00_설정/site_basin.csv` 의 `in_scope=1` 30곳(지도 폴더에 `site_basin.csv` 가 있으면 우선, `--sites`, `--all-sites`). 필수 열 `site,lat,lon,in_scope`.
- 실행: VS Code 에서 Run(여유 폭 km 입력, Enter = 3 km → SHP 선택창) 또는 `python3 extract_river_map.py [--river-shp 경로] [--basin 유역.gpkg] [--margin-m] [--out]`. 필요 패키지는 `requirements-map.txt`, 없으면 `.venv-map` 을 만들어 설치.
- 결과: `output/river_map_날짜_시각/` 의 `map.html`(인터넷 필요), `rivers.geojson`, `sites.geojson`, `area.geojson`.
- 부품: `read_sites`(CSV·지점 선택), `make_area`(사각형/유역 경계), `extract_rivers`(공간 필터·클립·WGS84), `render_map`(표시).
- 연구 범위 순서: ① 사각형 초안(인접 유역 하천 포함·먼 상류 잘림 가능) → ② 출처·기준연도 있는 공식 유역 경계로 대상 구역을 추려 단일 폴리곤 → ③ `--basin` 으로 다시 실행(경계 밖 지점은 이름 표시 후 종료) → ④ GIS·브라우저로 확인. 입력 파일 버전·유역 출처·명령을 기록.

## 7. 비밀값·git

- `*.env` 는 `Study/.gitignore` 로 제외(`!*.env.example` 은 올림). 대용량 원본(shp·geojson·xlsx)도 커밋하지 않는다.
- 커밋·푸시는 사용자가 요청할 때만. 저장소가 공개라면 예전에 올라갔던 키는 재발급.

## 8. 다음에 붙일 수 있는 것

- 수질측정망 자료를 한탄강(중권역 '한탄강'·'임진강하류') 분석 입력 형식으로 변환, 자료 없는 1지점 확인, VWorld 지점 좌표 결합, 다른 대권역(`BASIN` 만 바꿈)
- AWS(방재기상) 일자료(유역 평균 강수), 기상청 시간자료 `kma_sfctm3.php`(최대 31일), 홍수통제소 10분·1시간 자료와 댐·보 자료 — 강우 사건·상류 방류 분석용

## 변경 기록
- 2026-11-17 주제별 수집 폴더·개발지침 정리 / 11-18 수계지도 / 11-26 통합수집.py·total/·`통합수집.env` 통일·NFD 폴더 수정 / **11-26 지침 9개를 이 파일과 `Data/API_참고.md` 두 개로 통합, tms_analysis_1~3 을 연구사업 _archive zip 으로 옮김**
