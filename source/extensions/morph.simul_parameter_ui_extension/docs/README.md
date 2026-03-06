# Simul Parameter UI Extension [morph.simul_parameter_ui_extension]

Omniverse Kit에서 Simul 파라미터를 편집하고 JSON 파일로 저장하는 UI 익스텐션입니다.

## 주요 기능
- 상단 실행 버튼 3개: `ansys`, `simul_1`, `sinul_2`
- 행 단위 파라미터 편집:
  - `-` 버튼으로 행 삭제
  - `+` 버튼으로 행 추가
  - `key`, `value`, `type(string/number)` 입력
- JSON 저장:
  - `Save JSON` 클릭 시 경로/파일명 선택 팝업 표시
  - `number` 타입은 숫자(`int/float`)로 저장
  - `string` 타입은 문자열로 저장

## 검증 규칙
- 중복 key가 있으면 저장하지 않고 경고 팝업을 표시합니다.
- `number` 타입 value가 숫자가 아니면 저장하지 않고 경고 팝업을 표시합니다.
- key가 비어 있으면 자동으로 `item_1`, `item_2` 형태로 채웁니다.

## UI 구성
1. 첫 번째 줄: 상단 실행 버튼 (`ui.HStack`)
2. 두 번째 줄: `Save JSON` 버튼
3. 세 번째 줄: `+` 버튼
4. 네 번째 영역: 스크롤 가능한 파라미터 행 목록

## JSON 예시
```json
{
  "parameters": {
    "speed": 10,
    "name": "robot"
  }
}
```

## 코드 구조
- 메인 구현 파일:
  - `morph/simul_parameter_ui_extension/extension.py`
- 주요 상수:
  - 문자열 상수(버튼명, 팝업 문구, 기본 파일명)
  - UI 크기/레이아웃 상수(윈도우, 행, 스크롤, 팝업)
