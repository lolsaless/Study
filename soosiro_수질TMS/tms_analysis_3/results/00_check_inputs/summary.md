# 00. 입력 자료 점검

- 스크립트: `00_check_inputs.py`  ·  단계: 준비
- 실행 시각: 2026-11-05 06:32

## 목적

표준 자료의 형식을 검사하고, 지금 실행할 수 있는 분석과 자료를 기다리는 분석을 구분한다.

## 핵심 결과

- 분석 25개 중 25개 실행 가능, 0개 자료 대기

## 1. 표준 자료

| 양식 | 파일 | 상태 | 행 | 검사 |
|---|---|---|---|---|
| river_hourly | data/standard/river_hourly.csv.gz | 있음 | 1312848 | 통과 |
| river_daily | data/standard/river_daily.csv.gz | 있음 | 47731 | 통과 |
| weather_daily | data/standard/weather_daily.csv | 있음 | 145910 | 통과 |
| flow_daily | data/standard/flow_daily.csv | 있음 | 271776 | 통과 |
| obs_stations | data/standard/obs_stations.csv | 있음 | 2324 | 통과 |
| stations | data/meta/stations.csv | 있음 | 77 | 통과 |

## 2. 측정소 연결표(data/meta/stations.csv)

- weather_stn 입력된 측정소: 73
- flow_obscd 입력된 측정소: 11
- upstream_tms 입력된 측정소: 5
- stem 입력된 측정소: 33

연결 정보 중 '추정'은 link_note 에 표시돼 있다. 측정소 좌표(lat/lon)를 받으면 tools/link_stations.py 로 가장 가까운 기상·유량 지점을 다시 계산할 수 있다.

## 3. 분석별 실행 가능 여부

| 스크립트 | 단계 | 내용 | 필요 | 상태 |
|---|---|---|---|---|
| 10_data_quality.py | 기본 | 10. 자료 품질 진단 — 결측·고정값·급변·ND·부분측정일, 측정소×항목 품질등급(A~D), 동시 결측일 | river_daily | 실행 가능 |
| 11_descriptive.py | 기본 | 11. 기술통계·분포 — 측정소·수계별 수준과 변동, 영양염 제한 진단(TN:TP), 수계 비교 그림 | river_daily | 실행 가능 |
| 12_wq_grade.py | 기본 | 12. 생활환경기준 등급·목표 달성 — 연평균 등급 + '등급 판정 신뢰도'(블록 부트스트랩) + 일 초과빈도 | river_daily | 실행 가능 |
| 13_group_compare.py | 기본 | 13. 집단 비교 통계 — 수계 간(Kruskal–Wallis+Dunn, 측정소 단위), 계절 간(Friedman, 측정소 대응), 연도 간(대응 Wilcoxon + HL 이동량) | river_daily | 실행 가능 |
| 20_seasonality.py | 중급 | 20. 계절성 — 월별 기후값, 계절성 강도(월 요인 설명력 R²), 연중 최고 시기(원형 통계·Rayleigh 검정) | river_daily | 실행 가능 |
| 21_trend.py | 중급 | 21. 추세 — 계절 Mann–Kendall + Sen 기울기(%/년), FDR 보정, 자료 기간에 따른 검정력 안내 | river_daily | 실행 가능 |
| 22_diel_oxygen.py | 중급 | 22. 일주기(하루 안 변동)와 산소 대사 — DO·pH 일교차, 포화도, 저산소·과포화 일수, 광합성 지표와 Chl-a 의 관계, 시각별 패턴 | river_daily | 실행 가능 |
| 23_weekday_fingerprint.py | 중급 | 23. 요일 지문(인위 배출 신호) — 계절 제거 편차의 요일 패턴, 진폭·검정(FDR), 강우 사건일·공휴일 제외 | river_daily | 실행 가능 |
| 24_correlation_sync.py | 중급 | 24. 항목 간 관계와 측정소 간 동조성 — 측정소 내 Spearman·편상관(Chl-a~TP / 수온), 계절 제거 편차의 수계 공통 신호(PCA 설명비율) | river_daily | 실행 가능 |
| 25_changepoint.py | 중급 | 25. 변화점(계단형 수준 변화) — 계절 제거 주간 중앙값에 PELT, 같은 날 여러 항목이 함께 바뀐 '측정소 이벤트'(점검·교체 후보) | river_daily | 실행 가능 |
| 30_anomaly_events.py | 심화 | 30. 이상 사건 탐지·유형 분류 — 강건 z(계절 제거) + 다변량 Isolation Forest, 사건 유형(유출·조류·저산소·오염 의심·센서 의심), 광역 사건일 | river_daily | 실행 가능 |
| 31_typology.py | 심화 | 31. 측정소 유형화 — 수준·변동·계절·일주기·요일 특성 → 표준화 → PCA + 군집(K-means, 실루엣으로 k 선택) + Ward 계통도 | river_daily | 실행 가능 |
| 32_longitudinal.py | 심화 | 32. 상류→하류 종단 분석 — 줄기(stations.csv 의 stem·stem_order)별 농도 변화, 인접 구간 악화 검정, 사전백색화 교차상관으로 전달 시간 | river_daily, stem | 실행 가능 |
| 33_chla_drivers.py | 심화 | 33. 조류(Chl-a) 결정 요인 — 기계학습(그래디언트 부스팅 + 시간 블록 교차검증 + 순열 중요도 + 부분의존) & 분위회귀(상한 반응) | river_daily | 실행 가능 |
| 34_bloom_risk.py | 심화 | 34. 조류 고농도 위험 — 발생 빈도, 로지스틱 회귀(오즈비·95%CI), 3일 앞 조기경보 성능(2024 학습 → 2025 검증, AUC·기후값 대비) | river_daily | 실행 가능 |
| 35_extreme_value.py | 심화 | 35. 극값(POT–GPD) — 상위 5% 초과분 일반화 파레토 적합(사건 단위 묶기), 꼬리 두께 ξ, 1년·2년 재현 농도 | river_daily | 실행 가능 |
| 36_memory_spectral.py | 심화 | 36. 시계열 기억·주기 — 자기상관 e-folding 시간, DFA 지수(장기기억), 주기 스펙트럼(7일·연주기) 세기 | river_daily | 실행 가능 |
| 37_forecast_skill.py | 심화 | 37. 예측 가능성 — 1·3·7일 앞 예측: 지속(오늘값)·기후값 대비 그래디언트 부스팅의 기술점수(Skill), 시간 순 검증 | river_daily | 실행 가능 |
| 38_network_redundancy.py | 심화 | 38. 측정망 정보 중복도 — 한 측정소의 일 변동을 같은 수계 다른 측정소들로 재현(릿지 회귀, 시간 순 검증 R²) → 대체 가능성·고유 정보 순위 | river_daily | 실행 가능 |
| 40_weather_link.py | 연계 | 40. 기상 연계 — 강우 사건 반응(사건일/건기 비), 분포시차 회귀(비 온 뒤 며칠째 최대 반응), 기온–수온 민감도, 하천 정의 사건일 검증 | river_daily, weather_daily, weather_link | 실행 가능 |
| 41_flow_load.py | 연계 | 41. 유량 연계 — 농도–유량(C–Q) 관계로 오염원 유형 진단, 부하량, '고유량 10% 날'의 부하 비중, 부하지속곡선(LDC)으로 기준 초과가 생기는 유황 | river_daily, flow_daily, flow_link | 실행 가능 |
| 42_tms_link.py | 연계 | 42. 방류수 TMS × 하천 연계 — 상류 사업장 부하와 하천 농도의 요일 지문 일치, 시차 교차상관, (유량이 있으면) 건기 하천 부하 중 TMS 점오염 기여율 | river_daily, tms_link, tms | 실행 가능 |
| 43_load_balance.py | 연계 | 43. 부하 수지(연구 방향 1) — 하천 부하 − 상류 방류 TMS 부하 = 미계측 부하, 유황별 TMS 몫, 처리수 지배 하천, 자료 정합성 점검 | river_daily, flow_link, tms_link, tms | 실행 가능 |
| 44_wet_excess_load.py | 연계 | 44. 강우 초과 부하(연구 방향 2) — '희석만 됐을 때 예상 농도'보다 높은 만큼을 강우 유래 부하로 보고, 사건 유형(토사형 비점·유기물형 월류·희석형)을 가른다 | river_daily, weather_daily, weather_link | 실행 가능 |
| 45_facility_score.py | 연계 | 45. 처리시설 관리 평가(연구 방향 3) — 영역별 점수(기준 여유·안정성·강우 대응·자료 관리), 규모 보정·연도 안정성, 약점 진단, 원인 분석, 재정지원 우선순위(필요도×하천영향×개선여지) | tms | 실행 가능 |
