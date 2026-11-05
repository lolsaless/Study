# tms_analysis_3 — 국가수질자동측정망(4대강) 분석 패키지 v3

> **작업 전에 [`작업안내서.md`](작업안내서.md)를 먼저 읽으세요.** 필요한 자료는 [`자료요구서.md`](자료요구서.md), 진행상황은 [`PROJECT_STATUS.md`](PROJECT_STATUS.md).

## 1. 프로젝트 개요

| 항목 | 내용 |
|---|---|
| 목적 | 물환경정보시스템 국가수질자동측정망 시간자료로 4대강 하천·호소 수질의 수준·변동·원인을 **기본 → 중급 → 심화 → 연계** 순서로 분석하고, 방류수 TMS(tms_analysis_2)·기상·유량과 연결해 오염원(점·비점)을 추적한다. |
| 자료 | 한강 23 · 낙동강 31 · 금강 13 · 영산강 10 = **77개 측정소**, 2024-01-01 ~ 2025-12-31, 시간자료 131만 행 → 일자료 47,731행 / 항목: 수온·pH·EC·DO·탁도·TOC·TN·TP·Chl-a (+ 일부 NH₃-N·NO₃-N·PO₄-P·독성지수) |
| 보조 자료 | 기상청 ASOS 일자료(경기권 15지점), 한강홍수통제소 우량·수위·유량(경기권), 방류수 TMS(경기도, tms_analysis_2) — 모두 tms_analysis_2 에서 복사 |
| v2 와의 관계 | tms_analysis_2(경기도 방류수 TMS 분석)의 구조(번호별 독립 스크립트·summary.md·DIGEST)를 이어받아, 대상을 **하천 자동측정망**으로 옮기고 구조를 개선했다. v2 의 24번(TMS×하천 예비분석)을 4대강 규모로 일반화한 것이 42번이다. |

### v2 대비 개선점
1. **표준 양식(스키마) + 매핑 엔진**: 자료 형식이 바뀌어도 분석 코드는 그대로. 새 자료는 JSON 매핑 하나로 붙인다(`ingest/`, `tools/`).
2. **증분 수집**: 01번은 xlsx 파일마다 변환 결과를 캐시해 새 파일만 읽는다. 02번은 매핑을 자동으로 모두 실행한다.
3. **API 수집기**: 수질자동측정망(국립환경과학원)·기상청 ASOS 일자료·한강홍수통제소·WAMIS(`collectors/`).
4. **품질 연동**: 10번이 측정소×항목 품질등급(A~D)을 매기고, 이후 모든 분석이 D 등급을 자동 제외한다.
5. **핵심 결과 자동 요약**: 각 분석이 `rep.finding()` 으로 숫자 있는 결론을 남기고, 90번이 `results/00_핵심결과.md` 로 모은다.
6. **자료 대기 처리**: 자료가 없으면 분석이 멈추지 않고 '무엇이 필요한지'를 보고서로 남긴다. 00번이 실행 가능 여부를 표로 보여준다.
7. **통계 엄밀성**: 유사반복을 피한 측정소 단위 검정, 블록 부트스트랩, FDR, 효과크기(ε²·Cliff's δ·Kendall W), 시간 블록 교차검증.
8. **재현성**: 결과마다 `meta.json`(실행 시각·설정값·자료 기간), 실행 기록 `results/_run_log.txt`.

## 2. 폴더 구조

```
tms_analysis_3/
├─ 작업안내서.md  CLAUDE.md          ← 작업 전 먼저 읽기(사람·Claude)
├─ 자료요구서.md  PROJECT_STATUS.md  README.md
├─ config.py                         경로·항목·기준값(생활환경기준)·임계값
├─ run_all.py                        일괄 실행(단계·번호 선택)
├─ 00_check_inputs.py                입력 점검(표준 양식 검사, 실행 가능 분석 표)
├─ 01_ingest_nier.py  02_ingest_aux.py           준비: 원자료 → 표준 자료
├─ 10~13_*.py  20~25_*.py  30~38_*.py  40~42_*.py 분석(기본·중급·심화·연계)
├─ 90_build_digest.py                결과 취합
├─ core/                             공통 라이브러리
│   ├─ schema.py   표준 양식 정의·검사·저장   (python -m core.schema)
│   ├─ io.py       표준 자료 불러오기(load_daily, load_hourly, load_stations, wide, iter_series …)
│   ├─ stats.py    통계 함수(robust_z, fdr, deseason, kruskal_dunn, block_bootstrap, seasonal_mk, dfa_hurst …)
│   ├─ events.py   하천 자료로 강우 유출 사건일 정의
│   └─ report.py   Report(summary.md·CSV·그림·findings.json·meta.json)
├─ ingest/
│   ├─ mapper.py   매핑 엔진(JSON → 표준 양식)
│   └─ mappings/   *.json (nier_daily_v2, kma_asos_daily, hrfco_*, obs_stations_*, nier_api_hourly, _TEMPLATE)
├─ collectors/     API 수집기(collect_nier_api, collect_kma_asos_daily, collect_hrfco, collect_wamis_flow) + api_keys.env.example
├─ tools/          peek.py(파일 구조 보기) · make_mapping.py(매핑 초안) · link_stations.py(좌표로 연결) · _seed_stations.py
├─ templates/      station_info_request.csv(측정소 좌표 요청 양식)
├─ data/
│   ├─ raw/        원자료(수정 금지)
│   │   ├─ nier_auto_xlsx/2024_국가수질자동측정망/<권역>/*.xlsx, 2025_…   (물환경정보시스템에서 복사)
│   │   ├─ nier_auto_daily_v2/      기존 일별 변환본(merge_water_day.py 산출물, 대체 입력)
│   │   ├─ kma_asos/  hrfco/        기상·우량·수위·유량(tms_analysis_2 에서 복사)
│   ├─ inbox/      새 자료를 처음 넣는 곳(git 제외)
│   ├─ standard/   표준 자료: river_daily.csv.gz, river_hourly.csv.gz(git 제외), weather_daily.csv, flow_daily.csv, obs_stations.csv
│   └─ meta/       stations.csv(측정소 정보·연결표, 사람이 고침)
├─ work/           캐시(git 제외, 지워도 됨)
└─ results/        <번호_이름>/summary.md·CSV·figures/ · 00_핵심결과.md · 00_DIGEST_for_Claude.md
```

## 3. 설치와 실행

```bash
pip install -r requirements.txt
python run_all.py full        # 처음: 원자료 → 표준 자료 → 분석 전부 → 취합 (약 6~10분)
python run_all.py             # 이후: 분석만 다시
python run_all.py adv         # 단계만 (prep / basic / mid / adv / link)
python run_all.py 33 34       # 번호만
```
결과: `results/00_핵심결과.md` → 각 `results/<번호>/summary.md`. Claude 에게는 `작업안내서.md` + `results/00_핵심결과.md`(+ `00_DIGEST_for_Claude.md`, `results_for_claude.zip`).

## 4. 코드 사이의 관계

```
                     collectors/*.py ──(API)──┐
 물환경정보시스템 xlsx ─┐                      ▼
                      ▼               data/raw/<출처>/ ── ingest/mappings/*.json
               01_ingest_nier.py                 │            ▲ tools/make_mapping.py (초안)
                      │                 02_ingest_aux.py      │ tools/peek.py (구조 보기)
                      ▼                          ▼            │
      data/standard/river_hourly·river_daily   data/standard/weather·flow·obs_stations
                      │        data/meta/stations.csv ◄── tools/link_stations.py(좌표)
                      └──────────────┬───────────────┘
                                     ▼  core/schema.py(검사) · core/io.py(불러오기)
                          00_check_inputs.py (실행 가능 여부)
                                     ▼
   10 품질 ──► work/usable_pairs.csv ──► (io.load_daily 가 D 등급 자동 제외) ──► 11~42 전부
   30 이상사건 ──► work/regional_event_days.csv (강우일 대용)
   31 유형화  ──► work/station_types.csv
   core/events.py ──► 23·30·40·42 (하천 자료로 정의한 강우 사건일·건기일)
   tms_analysis_2/work/tms_clean.pkl ──► 42
                                     ▼
                     results/<번호>/summary.md · findings.json · meta.json
                                     ▼
                          90_build_digest.py → 00_핵심결과.md · DIGEST · zip
```

## 5. 스크립트별 사용법

모든 분석은 `python <파일>.py` 로 단독 실행된다(인자 없음). 필요한 표준 자료는 각 파일 맨 위 `REQUIRES` 에 있다.

### 준비

| 파일 | 하는 일 | 입력 → 출력 | 옵션 |
|---|---|---|---|
| `00_check_inputs.py` | 표준 자료 형식 검사, 분석별 실행 가능 여부 | data/standard, meta → results/00_check_inputs | |
| `01_ingest_nier.py` | 수질자동측정망 xlsx → 표준 시간·일 자료(ND·이상값 처리, 측정소 이름 통일, 증분 캐시) | data/raw/nier_auto_xlsx → river_hourly, river_daily | `--source daily_v2`, `--rebuild` |
| `02_ingest_aux.py` | `auto: true` 매핑 전부 실행, 새 측정소를 stations.csv 에 추가 | data/raw/* → weather_daily, flow_daily, obs_stations | `python 02_ingest_aux.py <매핑이름 일부>` |

### 1단계 기본

| 번호 | 분석 | 주요 방법 | 얻는 것 | 신규 |
|---|---|---|---|---|
| 10 | 자료 품질 진단 | 커버리지·부분측정일·일평균 고정값·급변(강건 z)·ND 비율·최장결측, 동시 결측일 | 측정소×항목 품질등급 A~D, 분석 사용 목록 | 등급 연동 |
| 11 | 기술통계·분포 | 분위수·CV·왜도, 수계 상자그림 | 수준·변동 순위, **TN:TP 영양염 제한 진단** | ● |
| 12 | 생활환경기준 등급 | 연평균 등급(하천·호소 기준), **블록 부트스트랩 등급 확률·목표 달성 확률** | 등급, 경계 측정소, 연도 간 등급 변화 | ● |
| 13 | 집단 비교 | Kruskal–Wallis+Dunn(측정소 단위), Friedman(계절), 대응 Wilcoxon·Hodges–Lehmann·Cliff's δ(연도) | 수계·계절·연도 차이와 효과크기 | ● |

### 2단계 중급

| 번호 | 분석 | 주요 방법 | 얻는 것 | 신규 |
|---|---|---|---|---|
| 20 | 계절성 | 월 요인 R², 월 기후값, **원형 통계(고농도 시기·Rayleigh)** | 계절성 강도, 다수와 시기가 다른 측정소 | ● |
| 21 | 추세 | 계절 Mann–Kendall·Sen, FDR, 측정소 부호 이항검정 | 증감 경향(2년 자료는 예비) | |
| 22 | 일주기·산소 대사 | 일 최소·최대, DO 포화도(Benson–Krause), 저산소·과포화일, 시각별 DO 패턴 | **광합성-호흡 세기, 새벽 저산소 위험** | ● |
| 23 | 요일 지문 | 계절 제거 편차의 요일 평균, Kruskal, FDR(강우 사건일·공휴일 제외) | 인위 배출 주기가 남은 측정소 | 4대강 확대 |
| 24 | 상관·동조성 | 측정소 내 Spearman, **수온 통제 편상관(Chl-a~TP)**, 수계 PC1 공통 신호 | 항목 연동, 광역 vs 국지 요인 비중 | ● |
| 25 | 변화점 | 월 기후값 제거 주 중앙값 + PELT | 계단형 변화, 여러 항목 동시 변화(장비 이벤트) | |

### 3단계 심화

| 번호 | 분석 | 주요 방법 | 얻는 것 | 신규 |
|---|---|---|---|---|
| 30 | 이상 사건 | 강건 z + **Isolation Forest**, 사건 유형 규칙(유출·조류·저산소·오염 의심·센서), 광역 사건일 | 사건 달력, '탁도 없이 농도↑' 오염 의심 사건 | ● |
| 31 | 측정소 유형화 | 특성(수준·변동·계절·일교차) → PCA + K-means(실루엣) + Ward | 유형과 소속, 바이플롯 | |
| 32 | 상류→하류 종단 | 같은 날 짝비교(Wilcoxon), **사전백색화 교차상관으로 전달 시간** | 악화 구간, 도달 시간 | ● |
| 33 | Chl-a 결정 요인 | **그래디언트 부스팅 + 월 블록 CV + 순열 중요도 + 부분의존**, **분위회귀(50·90%)** | 수계별 조류 요인, TP 탄력성(고농도일수록?) | ● |
| 34 | 조류 고농도 위험 | 빈도, **로지스틱 오즈비**, **3일 앞 조기경보 AUC(연도 분할 검증)** | 위험 조건, 경보 가능성 | ● |
| 35 | 극값 | POT–GPD(사건 묶기), 꼬리 ξ, 1·2년 재현 농도 | 충격형 측정소 | |
| 36 | 기억·주기 | e-folding, **DFA 지수**, 7일 주기 스펙트럼 | 관성, 장기기억, 인위 주기 | ● |
| 37 | 예측 가능성 | 지속·기후값 대비 그래디언트 부스팅 기술점수(1·3·7일, 시간 순 검증) | 며칠 앞까지 예측 가능한가 | ● |
| 38 | 측정망 중복도 | 다른 측정소로 재현(릿지, 시간 순 검증 R²) | 고유 정보 측정소 / 중복 측정소 | ● |

### 4단계 연계(자료가 있을 때 자동 실행, 없으면 '자료 대기')

| 번호 | 분석 | 필요 자료 | 얻는 것 | 신규 |
|---|---|---|---|---|
| 40 | 기상 연계 | weather_daily + stations.weather_stn | 강우 사건 배율, **분포시차(비 온 뒤 며칠째)**, **기온→수온 열 민감도**, 하천 정의 사건일 검증 | ● |
| 41 | 유량·부하 | flow_daily + stations.flow_obscd | **C–Q 유형(점/비점)**, 부하량, **고유량 10% 날 부하 비중**, **부하지속곡선** | ● |
| 42 | TMS × 하천 | tms_analysis_2 tms_clean.pkl + stations.upstream_tms | 요일 지문 일치, 시차 상관, **건기·강우기 TMS 기여율** | v2 24 확장 |

### 취합·도구

| 파일 | 사용법 |
|---|---|
| `90_build_digest.py` | 모든 결과 → `results/00_핵심결과.md`, `00_DIGEST_for_Claude.md`, `results_for_claude.zip` (run_all 마지막에 자동) |
| `tools/peek.py <파일·폴더>` | 새 자료 구조(인코딩·머리글·열 프로필) 출력 |
| `tools/make_mapping.py <파일> --target <양식> [--name 이름]` | 매핑 JSON 초안 자동 생성 |
| `ingest/mapper.py <매핑.json> [--dry-run] [--mode replace]` | 매핑 실행 |
| `tools/link_stations.py [--apply]` | 측정소 좌표로 가까운 기상·유량 지점 연결 |
| `collectors/collect_*.py --test` | API 응답 확인 후 수집(자료요구서 B·C) |
| `python -m core.schema [양식]` | 표준 양식 설명 |

## 6. 해석 시 주의

- 자료가 **2년**이다: 추세(21)·재현값(35)·예측(37)은 예비. 2026년 자료가 들어오면 다시 돌린다.
- 측정소 연결(줄기·기상지점·유량관측소·상류 사업장)은 현재 **추정**이다(`stations.csv` link_note). 32·40·41·42 결과는 연결 확인 뒤 확정한다.
- 생활환경기준·조류 기준값은 `config.py` 에서 현행 법령과 대조해 쓴다.
- TP 는 ND(검출한계 미만)가 많은 측정소에서 일평균이 높게 나온다(10번 표 참고).
