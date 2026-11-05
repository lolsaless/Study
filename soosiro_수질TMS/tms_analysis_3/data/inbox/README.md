# data/inbox — 새 자료를 처음 넣는 곳

1. 받은 파일을 `data/inbox/<자료이름>/` 에 그대로 넣는다(이 폴더 내용은 git 에 올라가지 않음).
2. `python tools/peek.py data/inbox/<자료이름>/` → 구조 확인(출력을 Claude 에게 붙여 넣어도 됨)
3. `python tools/make_mapping.py data/inbox/<자료이름>/ --target <표준양식> --name <매핑이름>` → 매핑 초안
4. `python ingest/mapper.py ingest/mappings/<매핑이름>.json --dry-run` → 확인 후 `--dry-run` 빼고 실행
5. 잘 되면 원본을 `data/raw/<출처>/` 로 옮기고 매핑의 inputs 경로·`"auto": true` 를 고친다 → 이후 02번이 자동 처리

자세한 절차: ../../작업안내서.md 3장
