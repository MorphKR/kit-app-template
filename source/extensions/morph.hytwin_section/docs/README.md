# Section Tool (`morph.hytwin_section`)

`morph.hytwin_section`은 Omniverse Kit 뷰포트에서 단면(Section Plane)을
직관적으로 생성/정렬/회전/관리할 수 있도록 제공하는 확장입니다.

## 주요 기능

- Section Tool 창 제공 (`Tools/Section` 메뉴)
- 단면 매니퓰레이터 표시/숨김 제어
- 빠른 정렬(X/Y/Z) 및 로컬 축 기준 회전
- 컷 방향 반전(Top/Bottom)
- 섹션 상태를 USD variant로 저장/복원
- Session Layer 기반 편집 지원 (`useSessionLayer`)

## UI 구성

- `SectionToolWindow`: 전체 패널 컨테이너
- `OptionsPanel`: 기본 옵션(예: 매니퓰레이터 표시)
- `QuickMovePanel`: 정렬/회전/컷 방향 조작
- `SectionManipulator`: 뷰포트 상호작용(클릭/호버/기즈모 선택)

## 내부 동작 요약

1. 확장 활성화 시 `SectionToolExtension`이 메뉴/이벤트를 등록합니다.
2. 창 표시 시 `SectionToolWindow`가 패널 UI와 구독을 초기화합니다.
3. `SectionManager`가 섹션 prim/variant 상태를 관리합니다.
4. `SectionModel`이 transform을 기반으로 section plane 값을 계산해 렌더 prim에 반영합니다.
5. Stage Open/Close 이벤트에 맞춰 상태를 초기화/정리합니다.

## 주요 설정

- `exts."morph.hytwin_section".alwaysDisplay`
  - `true`: 창이 닫혀도 섹션 표시 유지
  - `false`: 창이 닫히면 섹션 비활성화
- `exts."morph.hytwin_section".useSessionLayer`
  - `true`: Session Layer에 기록(원본 레이어 오염 최소화)
  - `false`: Root Layer에 기록
- `exts."morph.hytwin_section".menuPath`
  - 메뉴 노출 경로(기본 `Tools/Section`)

## 개발 참고

- 코드 루트: `morph/hytwin_section`
- 문서 상세: `docs/Overview.md`, `docs/SETTINGS.md`, `docs/CHANGELOG.md`
