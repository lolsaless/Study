# Claude 작업 지침 (tms_analysis_3)

**어떤 작업이든 시작하기 전에 `작업안내서.md` 를 먼저 끝까지 읽는다.** 그다음 `PROJECT_STATUS.md`, `results/00_핵심결과.md` 순서로 읽는다.

- 새 자료는 분석 코드를 고치지 말고 표준 양식으로 바꾸는 매핑(`ingest/mappings/*.json`)으로 붙인다(작업안내서 3-C).
- 표준 양식은 `core/schema.py`(확인: `python -m core.schema`). 분석은 `data/standard/`, `data/meta/` 만 읽는다.
- 필요한 자료가 없을 때는 `자료요구서.md` 에 항목을 추가·갱신한다.
- 코드를 바꾸면 해당 스크립트를 실제로 실행해 확인하고, 끝나면 `PROJECT_STATUS.md` 와 README 의 스크립트 표를 갱신한다.
- 인증키(`data/api_keys.env`)는 읽거나 출력하거나 커밋하지 않는다.
- 사용자는 환경 연구(수질 분석)와 Python/VS Code 데이터 분석을 한다. 설명은 한국어로, 통계 용어는 짧은 풀이와 함께 쓴다.
