# 수질 자료 OpenAPI 활용가이드 (요약)

> 원문: 공공데이터포털 「국립환경과학원_수질 DB」 OpenAPI 활용가이드(6.OpenAPI 활용가이드_수질DB_20221007.docx), 서비스 버전 1.1.
> 정리일 2026-11-17. 지점·항목 코드는 `수질측정망_지점코드.md`, 코드 작성 규칙은 `수질자료수집_개발지침.md` 참고.
> **인증키는 이 문서에 적지 않는다.** 키는 각 폴더의 `.env` 파일에만 둔다.

## 1. 서비스 공통

| 항목 | 내용 |
|---|---|
| 서비스 | WaterQualityService (수질 정보) |
| End Point | `https://apis.data.go.kr/1480523/WaterQualityService/<오퍼레이션>` (가이드에는 http, 실제는 https 사용) |
| 방식 | REST GET, 응답 XML(기본)·JSON (`resultType=xml/json`) |
| 인증 | `serviceKey` (공공데이터포털 일반 인증키) |
| 성능 | 평균 응답 5초, 초당 최대 30건 → 요청 사이 0.3초 정도 쉰다 |
| 정상 결과코드 | `00` NORMAL SERVICE |

공통 요청 변수: `serviceKey`(필수), `numOfRows`(페이지 크기, 기본 10), `pageNo`(기본 1), `resultType`.
공통 응답 틀(XML): `response/header/resultCode·resultMsg`, `response/body/items/item[]`, `body/numOfRows·pageNo·totalCount`.
키 오류·트래픽 초과는 `OpenAPI_ServiceResponse/cmmMsgHeader/returnAuthMsg`(예: `SERVICE_KEY_IS_NOT_REGISTERED_ERROR`)로 온다.

### 오퍼레이션 목록

| # | 오퍼레이션 | 내용 | 갱신 주기 |
|---|---|---|---|
| 1 | `getWaterMeasuringList` | 물환경 수질측정망 운영결과 (월 1~4회 채수 분석) | 월 1회, 관보 게재 시 약 2개월 전 자료 공개 |
| 2 | `getSgisDrinkWaterList` | 토양지하수 먹는물 공동시설(약수터) | 분기 1회 |
| 3 | `getRealTimeWaterQualityList` | 수질자동측정망 운영결과 (시간 자료, 70개소) | 월 1회, 매월 초 3개월 전 자료 공개 |
| 4 | `getRadioActiveMaterList` | 방사성물질측정망 | 반기 1회 |
| 5 | `getWaterMeasuringListMavg` | 물환경 수질측정망 월평균 | 월 1회 |

## 2. getWaterMeasuringList — 물환경 수질측정망

### 요청 변수

| 변수 | 설명 | 예 |
|---|---|---|
| `ptNoList` | 지점코드, 여러 개는 쉼표. 항목 크기 100자 → 7자리 코드 **10개씩** 묶어 요청 | `1001A05,1001A10` |
| `wmyrList` | 측정연도, 쉼표로 여러 개 | `2025,2026` |
| `wmodList` | 측정월(두 자리), 쉼표로 여러 개 | `01,02,03` |

### 응답 열

- 지점·시점: `ptNo` 지점코드, `ptNm` 지점명, `addr` 주소, `orgNm` 조사기관, `wmyr` 연도, `wmod` 월, `wmwk` 검사회차, `wmdep` 수심(m), `wmcymd` 검사일자(`2015.08.10` 형식)
- 좌표: `lonDgr·lonMin·lonSec`, `latDgr·latMin·latSec` (도·분·초 → 십진수 = 도 + 분/60 + 초/3600)
- 측정값(단위 mg/L, 예외만 표시):

| 열 | 항목 | 열 | 항목 | 열 | 항목 |
|---|---|---|---|---|---|
| itemLvl | 수위(m) | itemAmnt | 유량(㎥/s) | itemTemp | 수온(℃) |
| itemPh | pH | itemDoc | DO | itemBod | BOD |
| itemCod | COD | itemSs | SS | itemToc | TOC |
| itemTn | T-N | itemTp | T-P | itemDtn | 용존총질소 |
| itemDtp | 용존총인 | itemNo3n | 질산성질소 | itemNh3n | 암모니아성질소 |
| itemPop | 인산염인 | itemCloa | 클로로필-a(mg/㎥) | itemEc | 전기전도도(µS/cm) |
| itemTcoli | 총대장균군(/100mL) | itemEcoli | 분원성대장균군(/100mL) | itemTrans | 투명도(가이드엔 mg/L, 실제 m로 추정) |
| itemCl | 염소이온 | itemFl | 불소 | itemCol | 색도(도) |
| itemCd | 카드뮴 | itemCn | 시안 | itemPb | 납 |
| itemCr6 | 6가크롬 | itemCr | 크롬 | itemAs | 비소 |
| itemHg | 수은 | itemCu | 구리 | itemZn | 아연 |
| itemNi | 니켈 | itemBa | 바륨 | itemSe | 셀레늄 |
| itemMn | 용해성 망간 | itemFe | 용해성 철 | itemAntimon | 안티몬 |
| itemAbs | 음이온계면활성제 | itemPcb | PCB | itemOp | 유기인 |
| itemPhenol | 페놀류 | itemNhex | 노말헥산추출물질 | itemTce | 트리클로로에틸렌 |
| itemPce | 테트라클로로에틸렌 | itemCcl4 | 사염화탄소 | itemDceth | 1,2-다이클로로에탄 |
| itemDcm | 다이클로로메탄 | itemBenzene | 벤젠 | itemChcl3 | 클로로포름 |
| itemDehp | DEHP | itemDiox | 1,4-다이옥세인 | itemHcho | 포름알데히드 |
| itemHcb | 헥사클로로벤젠 | | | | |

예: `.../getWaterMeasuringList?serviceKey=키&numOfRows=1000&pageNo=1&resultType=xml&ptNoList=1001A05,1001A10&wmyrList=2025`

## 3. getRealTimeWaterQualityList — 수질자동측정망

### 요청 변수

| 변수 | 설명 | 예 |
|---|---|---|
| `siteId` | 측정소코드, 쉼표로 여러 개 | `S01001` |
| `startDate` / `endDate` | `yyyyMMddHHmmss` 14자리, **둘 다** 넣어야 적용 | `20260101000000` / `20260131235959` |

`numOfRows`·`pageNo`가 필수로 표시됨. 시간 자료라 측정소 1개·1개월(약 744행)씩 `numOfRows=1000`으로 요청하면 보통 한 페이지.

### 응답 열

`siteId`, `siteName`, `msrDate`(조사시간), `m01`~`m100`(항목별 측정값). 항목코드 표는 `수질측정망_지점코드.md` 1절.
주요 항목: 수온 m02/m38/m69(℃), pH m03/m39/m70, EC m04/m40/m71(µS/cm), DO m05/m41/m72(mg/L), TOC m06/m81(mg/L), 총질소 m27, 총인 m28(mg/L), 클로로필-a m29(mg/㎥), 탁도 m79/m80/m73(NTU), 인산염인 m35, 암모니아성질소 m36, 질산성질소 m37.
- `-999` = 정량한계 미만, `n/a` = 측정 안 함.
- 같은 항목이 측정기 계열(1·2·3)별 칸으로 나뉘어 측정소마다 값이 있는 칸이 다르다.

## 4. 기타 오퍼레이션 (필요 시 원문 확인)

- `getSgisDrinkWaterList`: 요청 `yyyy`, `sido`, `period`(1/4, 2/4, 7월…), `sgg`, `legacyCodeNo`(PUB_xxxx), `spotNm`. 응답은 미생물·건강상 유해물질·심미 항목 등 약수터 검사 결과.
- `getRadioActiveMaterList`, `getWaterMeasuringListMavg`: 활용가이드 2.1.6·2.1.7 참고(요청 형식은 getWaterMeasuringList와 비슷).

## 5. 주의할 점

1. **인증키 인코딩**: 포털의 '인코딩 키'(`%2F`, `%3D` 포함)를 `requests`의 params에 그대로 넣으면 두 번 인코딩되어 키 오류가 난다. `urllib.parse.unquote()`로 풀어서 넣는다(디코딩 키는 그대로).
2. **XML로 받는다**: 활용가이드가 XML 기준으로 정의되어 있고 JSON은 구조가 오퍼레이션마다 달라질 수 있다.
3. **자료 없음**: 결과코드 `03`(NODATA) 또는 item 0건. 미공개 기간이면 정상이다.
4. **공개 지연**: 자동측정망은 약 3개월, 수질측정망은 약 2개월 늦게 공개된다. 최근 달은 다시 받는 구조로 만든다.

## 6. VWorld 2D 데이터 API (지도·지점 좌표용)

- 요청: `https://api.vworld.kr/req/data?service=data&version=2.0&request=GetFeature&data=<레이어ID>&key=<키>&format=json&crs=EPSG:4326&geomFilter=BOX(minx,miny,maxx,maxy)&size=1000&page=1`
- 수질측정망 하천수 지점: 서비스ID `weissitema` → 레이어ID `LT_P_WEISSITEMA`로 **추정**(안내 페이지 직접 확인 못 함, 첫 실행으로 확인 필요).
- `geomFilter` 또는 `attrFilter` 필수, `size` 최대 1000. 전국은 1° 격자로 나눠 받고 feature id로 중복 제거.
- 응답: `response.status`(OK/NOT_FOUND/ERROR), `response.page.total`, `response.result.featureCollection.features[]`.
- 키는 `.env`의 `VWORLD_API_KEY`, 필요 시 `VWORLD_DOMAIN`.
