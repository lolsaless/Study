# 02. 보조 자료 표준화(기상·유량·관측소)

- 스크립트: `02_ingest_aux.py`  ·  단계: 준비
- 실행 시각: 2026-11-05 05:57

## 목적

매핑 JSON 으로 보조 자료를 표준 양식으로 바꾸고, 측정소 연결표를 점검한다.

## 핵심 결과

- river_hourly: 1,312,848행 · 77개 지점/측정소 · -
- river_daily: 47,731행 · 77개 지점/측정소 · 2024-01-01~2025-12-31
- weather_daily: 145,910행 · 160개 지점/측정소 · 2024-01-01~2026-06-30
- flow_daily: 271,776행 · 298개 지점/측정소 · 2024-01-01~2026-06-30
- obs_stations: 2,324행 · 3개 지점/측정소 · -
- stations: 77행 · 77개 지점/측정소 · -

## 1. 매핑 실행 결과

| 매핑 | 대상 | 행 | 상태 |
|---|---|---|---|
| hrfco_flow_daily.json | flow_daily | 271776 | OK |
| hrfco_rain_daily.json | weather_daily | 132240 | OK |
| kma_asos_daily.json | weather_daily | 13670 | OK |
| obs_stations_asos.json | obs_stations | 160 | OK |
| obs_stations_hrfco.json | obs_stations | 1420 | OK |
| obs_stations_hrfco_rain.json | obs_stations | 744 | OK |

## 2. 표준 자료 현황

| 양식 | 파일 | 행 | 개체 수 | 기간 |
|---|---|---|---|---|
| river_hourly | data/standard/river_hourly.csv.gz | 1312848 | 77 |  |
| river_daily | data/standard/river_daily.csv.gz | 47731 | 77 | 2024-01-01~2025-12-31 |
| weather_daily | data/standard/weather_daily.csv | 145910 | 160 | 2024-01-01~2026-06-30 |
| flow_daily | data/standard/flow_daily.csv | 271776 | 298 | 2024-01-01~2026-06-30 |
| obs_stations | data/standard/obs_stations.csv | 2324 | 3 |  |
| stations | data/meta/stations.csv | 77 | 77 |  |

## 3. 측정소 연결표(data/meta/stations.csv)

- stations.csv 'lat' 채워진 측정소: 0
- stations.csv 'weather_stn' 채워진 측정소: 73
- stations.csv 'flow_obscd' 채워진 측정소: 11
- stations.csv 'upstream_tms' 채워진 측정소: 5
- stations.csv 'stem' 채워진 측정소: 33
