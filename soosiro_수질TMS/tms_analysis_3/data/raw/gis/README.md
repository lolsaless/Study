# data/raw/gis — 유역 경계 파일

표준유역(또는 수질오염총량 단위유역·중권역) 경계를 **GeoJSON, 좌표계 EPSG:4326(WGS84)** 으로 넣는다.
(shp 는 geopandas 가 설치돼 있으면 그대로 읽는다.)

- 출처: 물환경정보시스템 또는 WAMIS 의 표준유역 경계(자료요구서 A-3)
- 변환: QGIS → 레이어 우클릭 → 내보내기 → 객체 저장 → 형식 GeoJSON, 좌표계 EPSG:4326
- 사용: `python tools/assign_upstream.py --code-col <구역코드 열 이름> --auto` (RESEARCH_REVIEW.md 1.6)
