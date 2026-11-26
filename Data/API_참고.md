# 수집 API 참고 (요청·응답 형식)

> 2026-11-26 통합: 예전 `수질API_활용가이드.md`·`강수량_API활용가이드.md`·`수위_API활용가이드.md` 를 그대로 합쳤다(옛 판 `_backup/지침통합전_20261126.zip`).
> 요청 코드를 새로 짜거나 응답 형식 오류를 고칠 때만 해당 절을 연다. 수집 규칙·실행법은 `Study/README.md`, 지점·항목 코드는 `수질측정망/site_code/수질측정망_지점코드.md`.
> **인증키는 이 문서에 적지 않는다.** 통합수집은 `Data/통합수집.env`, 주제 코드를 따로 돌릴 때는 각 폴더 `.env`.

---

## A. 공공데이터포털 — 국립환경과학원 수질 DB (수질측정망·수질자동측정망) + VWorld

원문: 공공데이터포털 「국립환경과학원_수질 DB」 OpenAPI 활용가이드(서비스 버전 1.1, 20221007). 정리 2026-11-17.

### 1. 서비스 공통

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

#### 오퍼레이션 목록

| # | 오퍼레이션 | 내용 | 갱신 주기 |
|---|---|---|---|
| 1 | `getWaterMeasuringList` | 물환경 수질측정망 운영결과 (월 1~4회 채수 분석) | 월 1회, 관보 게재 시 약 2개월 전 자료 공개 |
| 2 | `getSgisDrinkWaterList` | 토양지하수 먹는물 공동시설(약수터) | 분기 1회 |
| 3 | `getRealTimeWaterQualityList` | 수질자동측정망 운영결과 (시간 자료, 70개소) | 월 1회, 매월 초 3개월 전 자료 공개 |
| 4 | `getRadioActiveMaterList` | 방사성물질측정망 | 반기 1회 |
| 5 | `getWaterMeasuringListMavg` | 물환경 수질측정망 월평균 | 월 1회 |

### 2. getWaterMeasuringList — 물환경 수질측정망

#### 요청 변수

| 변수 | 설명 | 예 |
|---|---|---|
| `ptNoList` | 지점코드, 여러 개는 쉼표. 항목 크기 100자 → 7자리 코드 **10개씩** 묶어 요청 | `1001A05,1001A10` |
| `wmyrList` | 측정연도, 쉼표로 여러 개 | `2025,2026` |
| `wmodList` | 측정월(두 자리), 쉼표로 여러 개 | `01,02,03` |

#### 응답 열

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

### 3. getRealTimeWaterQualityList — 수질자동측정망

#### 요청 변수

| 변수 | 설명 | 예 |
|---|---|---|
| `siteId` | 측정소코드, 쉼표로 여러 개 | `S01001` |
| `startDate` / `endDate` | `yyyyMMddHHmmss` 14자리, **둘 다** 넣어야 적용 | `20260101000000` / `20260131235959` |

`numOfRows`·`pageNo`가 필수로 표시됨. 시간 자료라 측정소 1개·1개월(약 744행)씩 `numOfRows=1000`으로 요청하면 보통 한 페이지.

#### 응답 열

`siteId`, `siteName`, `msrDate`(조사시간), `m01`~`m100`(항목별 측정값). 항목코드 표는 `수질측정망/site_code/수질측정망_지점코드.md` 1절.
주요 항목: 수온 m02/m38/m69(℃), pH m03/m39/m70, EC m04/m40/m71(µS/cm), DO m05/m41/m72(mg/L), TOC m06/m81(mg/L), 총질소 m27, 총인 m28(mg/L), 클로로필-a m29(mg/㎥), 탁도 m79/m80/m73(NTU), 인산염인 m35, 암모니아성질소 m36, 질산성질소 m37.
- `-999` = 정량한계 미만, `n/a` = 측정 안 함.
- 같은 항목이 측정기 계열(1·2·3)별 칸으로 나뉘어 측정소마다 값이 있는 칸이 다르다.

### 4. 기타 오퍼레이션 (필요 시 원문 확인)

- `getSgisDrinkWaterList`: 요청 `yyyy`, `sido`, `period`(1/4, 2/4, 7월…), `sgg`, `legacyCodeNo`(PUB_xxxx), `spotNm`. 응답은 미생물·건강상 유해물질·심미 항목 등 약수터 검사 결과.
- `getRadioActiveMaterList`, `getWaterMeasuringListMavg`: 활용가이드 2.1.6·2.1.7 참고(요청 형식은 getWaterMeasuringList와 비슷).

### 5. 주의할 점

1. **인증키 인코딩**: 포털의 '인코딩 키'(`%2F`, `%3D` 포함)를 `requests`의 params에 그대로 넣으면 두 번 인코딩되어 키 오류가 난다. `urllib.parse.unquote()`로 풀어서 넣는다(디코딩 키는 그대로).
2. **XML로 받는다**: 활용가이드가 XML 기준으로 정의되어 있고 JSON은 구조가 오퍼레이션마다 달라질 수 있다.
3. **자료 없음**: 결과코드 `03`(NODATA) 또는 item 0건. 미공개 기간이면 정상이다.
4. **공개 지연**: 자동측정망은 약 3개월, 수질측정망은 약 2개월 늦게 공개된다. 최근 달은 다시 받는 구조로 만든다.

### 6. VWorld 2D 데이터 API (지도·지점 좌표용)

- 요청: `https://api.vworld.kr/req/data?service=data&version=2.0&request=GetFeature&data=<레이어ID>&key=<키>&format=json&crs=EPSG:4326&geomFilter=BOX(minx,miny,maxx,maxy)&size=1000&page=1`
- 수질측정망 하천수 지점: 서비스ID `weissitema` → 레이어ID `LT_P_WEISSITEMA`로 **추정**(안내 페이지 직접 확인 못 함, 첫 실행으로 확인 필요).
- `geomFilter` 또는 `attrFilter` 필수, `size` 최대 1000. 전국은 1° 격자로 나눠 받고 feature id로 중복 제거.
- 응답: `response.status`(OK/NOT_FOUND/ERROR), `response.page.total`, `response.result.featureCollection.features[]`.
- 키는 `.env`의 `VWORLD_API_KEY`, 필요 시 `VWORLD_DOMAIN`.

---

## B. 기상청 API허브 — ASOS 지상관측

원문: https://apihub.kma.go.kr → 지상관측. 정리 2026-11-17. ✔ 공식 목록 확인 / △ 공개 코드·추정 / ✖ 미확인(첫 실행으로 확인).

### 1. 공통

| 항목 | 내용 |
|---|---|
| 기본 주소 | `https://apihub.kma.go.kr/api/typ01/url/<파일>.php` ✔ |
| 인증 | 쿼리 변수 `authKey=<인증키>` ✔ (공공데이터포털 `serviceKey` 와 다름) |
| 활용신청 | API허브 로그인 → 각 API 의 '활용신청'을 해야 그 API 를 부를 수 있음 ✔ |
| 응답 | 고정 폭 텍스트. `#` 으로 시작하는 줄 = 설명·머리글, 그 밖의 줄 = 자료 ✔. 글자 인코딩 EUC-KR 가능성 △(코드는 utf-8 → cp949 순으로 읽음) |
| 설명 줄 | `help=1` 이면 열 설명을 함께 줌 ✔ |
| 결측 코드 | 공식 목록에 정의 없음 ✖ (보통 -9 / -99 로 알려져 있음 △) |
| 호출 한도 | 확인 못 함 ✖ |

### 2. 일자료 기간 조회 — `kma_sfcdd3.php` (수집 코드가 쓰는 것)

예(공식):
```
https://apihub.kma.go.kr/api/typ01/url/kma_sfcdd3.php?tm1=20151211&tm2=20151214&stn=108&help=1&authKey=<인증키>
```

| 변수 | 뜻 | 예 |
|---|---|---|
| `tm1` | 시작일 YYYYMMDD ✔ | 20240101 |
| `tm2` | 끝일 YYYYMMDD ✔ | 20240131 |
| `stn` | 지점번호, `0` = 전체 지점 △ | 0, 95, 108 |
| `help` | 1 = 설명 줄 포함 ✔ | 1 |
| `authKey` | 인증키 ✔ | |

- 기간 한도: 일자료는 공식 목록에 한도 표시가 없음. 수집 코드는 안전하게 **한 달씩** 요청 ✖
- 시간자료 기간 조회(`kma_sfctm3.php`)는 **최대 31일** ✔

#### 출력 열(56개, 공식 순서) ✔

| # | 열 | 뜻(단위) | # | 열 | 뜻(단위) |
|---|---|---|---|---|---|
| 1 | TM | 관측일(KST) | 29 | PS_MAX_TM | 최고 해면기압 시각 |
| 2 | STN | 지점번호 | 30 | PS_MIN | 최저 해면기압(hPa) |
| 3 | WS_AVG | 일 평균 풍속(m/s) | 31 | PS_MIN_TM | 최저 해면기압 시각 |
| 4 | WR_DAY | 일 풍정(m) | 32 | CA_TOT | 전운량(1/10) |
| 5 | WD_MAX | 최대풍향 | 33 | SS_DAY | 일조합(hr) |
| 6 | WS_MAX | 최대풍속(m/s) | 34 | SS_DUR | 가조시간(hr) |
| 7 | WS_MAX_TM | 최대풍속 시각 | 35 | SS_CMB | 캄벨 일조(hr) |
| 8 | WD_INS | 최대순간풍향 | 36 | SI_DAY | 일사합(MJ/m²) |
| 9 | WS_INS | 최대순간풍속(m/s) | 37 | SI_60M_MAX | 최대 1시간일사(MJ/m²) |
| 10 | WS_INS_TM | 최대순간풍속 시각 | 38 | SI_60M_MAX_TM | 그 시각 |
| 11 | **TA_AVG** | 일 평균기온(℃) | 39 | **RN_DAY** | 일 강수량(mm) |
| 12 | **TA_MAX** | 최고기온(℃) | 40 | RN_D99 | 9-9 강수량(mm) |
| 13 | TA_MAX_TM | 최고기온 시각 | 41 | RN_DUR | 강수계속시간(hr) |
| 14 | **TA_MIN** | 최저기온(℃) | 42 | RN_60M_MAX | 1시간 최다강수량(mm) |
| 15 | TA_MIN_TM | 최저기온 시각 | 43 | RN_60M_MAX_TM | 그 시각 |
| 16 | TD_AVG | 평균 이슬점온도(℃) | 44 | RN_10M_MAX | 10분 최다강수량(mm) |
| 17 | TS_AVG | 평균 지면온도(℃) | 45 | RN_10M_MAX_TM | 그 시각 |
| 18 | TG_MIN | 최저 초상온도(℃) | 46 | RN_POW_MAX | 최대 강우강도(mm/h) |
| 19 | HM_AVG | 평균 상대습도(%) | 47 | RN_POW_MAX_TM | 그 시각 |
| 20 | HM_MIN | 최저습도(%) | 48 | SD_NEW | 최심 신적설(cm) |
| 21 | HM_MIN_TM | 최저습도 시각 | 49 | SD_NEW_TM | 그 시각 |
| 22 | PV_AVG | 평균 수증기압(hPa) | 50 | SD_MAX | 최심 적설(cm) |
| 23 | EV_S | 소형 증발량(mm) | 51 | SD_MAX_TM | 그 시각 |
| 24 | EV_L | 대형 증발량(mm) | 52 | TE_05 | 0.5m 지중온도(℃) |
| 25 | FG_DUR | 안개계속시간(hr) | 53 | TE_10 | 1.0m 지중온도(℃) |
| 26 | PA_AVG | 평균 현지기압(hPa) | 54 | TE_15 | 1.5m 지중온도(℃) |
| 27 | PS_AVG | 평균 해면기압(hPa) | 55 | TE_30 | 3.0m 지중온도(℃) |
| 28 | PS_MAX | 최고 해면기압(hPa) | 56 | TE_50 | 5.0m 지중온도(℃) |

시각 열(`*_TM`)은 시분(HHMM) 4자리.

### 3. 지점정보

| 주소 | 상태 |
|---|---|
| `stn_inf.php?inf=SFC&stn=&tm=YYYYMMDDHHMM&help=1` | ✖ 수집 코드가 먼저 시도 |
| `kma_stnlist.php?stn=0&help=1` | △ 공개 코드(kma-mcp)에서 쓰는 이름. 두 번째로 시도 |
| `api/typ02/openApi/SfcMtlyInfoService/getSfcStnLstTbl?pageNo=1&numOfRows=10&dataType=XML&year=2016&month=09` | ✔ 공식 목록(월별 지점 목록, 출력 stn_id·stn_ko·lat·lon·ht 등). 위 둘이 안 되면 이것으로 바꿀 것 |

### 4. 연구에서 쓰는 주요 ASOS 지점

| 번호 | 지점 | 비고 |
|---|---|---|
| 95 | 철원 | 한탄강 상류, 연구 기온 자료 |
| 98 | 동두천 | 신천 유역, 연구 기온 자료 |
| 99 | 파주 | 임진강 하류 |
| 108 | 서울 | |
| 202 | 양평 | |
| 101 | 춘천 | |

### 5. 오류 대응

| 증상 | 원인·대응 |
|---|---|
| HTTP 401/403, '인증' 문구 | 키 오류 또는 해당 API 활용신청 안 함 → API허브에서 일자료 활용신청 확인 |
| 자료 줄 0개, 설명 줄만 | 기간·지점에 자료 없음(정상일 수 있음) |
| 글자 깨짐 | EUC-KR. 코드는 자동 처리 |
| 값 개수 ≠ 56 | 열 구성이 바뀜 → `COL_번호` 로 저장되니 `--test` 출력과 함께 Claude 에게 전달 |
| 행정망 PC 에서 접속 안 됨 | 인터넷 PC(맥)에서 실행 |

---

## C. 한강홍수통제소 Open API — 수위·유량·우량

원문: https://www.hrfco.go.kr/web/openapiPage/reference.do . 정리 2026-11-17. ✔ 공식 레퍼런스 확인 / △ 이전 코드·추정 / ✖ 미확인.

### 1. 공통

| 항목 | 내용 |
|---|---|
| 주소 형식 | `https://api.hrfco.go.kr/{ServiceKey}/{HydroType}/{DataType}/{TimeType}/{관측소코드}/{시작}/{끝}.{json\|xml}` ✔ |
| 인증 | 주소 **경로 안**에 인증키(쿼리 변수 아님) ✔ → 오류 메시지·로그에 키가 찍히지 않게 주의 |
| 인증키 발급 | 한강홍수통제소 홈페이지 → 정보공개 → 오픈API 사용 신청 ✔ |
| 응답 | JSON 또는 XML ✔. JSON 은 `{"content": [ … ]}` △(이전 코드 기준) |
| 자료 성격 | **실시간 자료**(확정 전) ✔ |
| 호출 한도 | 분당 1,000건이라는 사용자 글이 있음 △. 공식 확인 못 함 ✖ |

#### HydroType / DataType / TimeType

| 변수 | 값 | 뜻 |
|---|---|---|
| HydroType | `waterlevel` ✔ | 수위(유량 포함) |
| | `rainfall` ✔ | 강수량 |
| | `dam`, `bo` ✔ | 댐, 보 |
| DataType | `info` ✔ | 관측소 제원 |
| | `list` ✔ | 실시간 자료(기간 조회) |
| TimeType | `10M` ✔ | 10분 — 기간 **최대 1개월**, 날짜 `yyyyMMddHHmm` ✔ |
| | `1H` ✔ | 1시간 |
| | `1D` ✔ | 1일 — 날짜 형식·최대 기간 ✖ (코드는 `yyyyMMdd` 로 보내고 31일씩 요청) |
| 관측소코드 | 선택 ✔ | 빼면 전체 관측소의 **최종 시각** 자료 |

### 2. 수집 코드가 쓰는 요청

| 용도 | 주소 |
|---|---|
| 수위 관측소 제원 | `https://api.hrfco.go.kr/{키}/waterlevel/info.json` |
| 우량 관측소 제원 | `https://api.hrfco.go.kr/{키}/rainfall/info.json` |
| 수위·유량 일자료 | `https://api.hrfco.go.kr/{키}/waterlevel/list/1D/1022670/20240101/20240131.json` |
| 강수량 일자료 | `https://api.hrfco.go.kr/{키}/rainfall/list/1D/10224020/20240101/20240131.json` |

공식 예(10분 기간별): `https://api.hrfco.go.kr/ServiceKey/waterlevel/list/10M/1018683/202503230710/202503240710.xml` ✔ (1018683 = 서울시 한강대교)

### 3. 응답 항목

#### 수위 `waterlevel/list`
| 항목 | 뜻 | 상태 |
|---|---|---|
| `wlobscd` | 수위 관측소 코드 | △ |
| `ymd` / `ymdh` / `ymdhm` | 관측 일 / 시 / 10분 (1D 는 `ymd` 로 추정) | △ |
| `wl` | 수위(m) | ✔ |
| `fw` | **유량(m³/s)** | ✔ |

#### 강수량 `rainfall/list`
| 항목 | 뜻 | 상태 |
|---|---|---|
| `rfobscd` | 우량 관측소 코드 | △ |
| `ymd` … | 관측 시각 | △ |
| `rf` | 강수량(mm) | △ |

#### 제원 `info`
| 항목 | 뜻 | 상태 |
|---|---|---|
| `wlobscd` / `rfobscd` | 관측소 코드 | △ |
| `obsnm` | 관측소명(예: 연천군(신천교)) | △ |
| `agcnm` | 관리기관 | △ |
| `addr`, `etcaddr` | 주소 | △ |
| `lat`, `lon` | 위도·경도, **도-분-초 문자열**(`37-59-01`) → 코드가 십진수로 변환 | △ |
| `attwl`, `wrnwl`, `almwl`, `srswl` | 관심·주의·경보·심각 기준수위 | △ |

대소문자: 문서에 `FW`·`WL` 처럼 대문자로도 표기됨 → 코드는 모든 열 이름을 소문자로 맞춰 읽음.

### 4. 알아 둘 점

- **유량 = 수위로 환산한 값**: 수위만 재는 관측소는 유량이 비거나 0 (예: 고탄교 1022666 은 전 기간 0).
- **같은 수위, 다른 값**: 공개 사례에서 같은 관측소 수위가 다른 자료원과 기준(표고 vs 수위표 영점)이 달라 보인 경우가 있음 △ → 다른 출처와 합칠 때 기준 확인.
- **실시간 자료 보정**: 나중에 값이 바뀔 수 있어 코드는 최근 60일을 다시 받음.
- **행정망 PC**: 외부 API 가 막힐 수 있으니 인터넷 PC(맥)에서 실행.

### 5. 오류 대응

| 증상 | 원인·대응 |
|---|---|
| HTTP 401/403, 응답에 key·인증 문구 | 인증키 확인(`홍수통제소.env`) |
| 응답이 JSON 이 아님 | 주소 형식 오류 또는 서버 오류 → `--test` 출력 전달 |
| `content` 가 빈 목록 | 날짜 형식 불일치 또는 그 기간 자료 없음. 코드는 다른 날짜 형식으로 한 번 더 시도 |
| 일부 관측소만 실패 | 관측소 코드 폐지·변경 → `--list` 로 현재 제원 확인 |
