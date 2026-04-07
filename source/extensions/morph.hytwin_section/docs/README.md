# Section Tool (`morph.hytwin_section`)

`morph.hytwin_section`은 Omniverse Kit 뷰포트에서 단면(Section Plane)을
생성/조작/유지하기 위한 확장입니다.
단순 UI 제공을 넘어서, viewport별 scene 동기화와 USD 데이터 반영까지 포함합니다.

## 확장이 해결하는 문제

- 씬 내부를 확인하기 위한 단면을 빠르게 켜고 끄고 싶다.
- 단면 평면을 X/Y/Z 축 기준으로 맞추거나 세밀하게 회전하고 싶다.
- 여러 뷰포트(분할 화면)에서 동일한 섹션 도구를 안정적으로 사용하고 싶다.
- Stage를 닫거나 다시 열어도 섹션 상태가 안전하게 초기화되길 원한다.
- 원본 레이어 오염을 줄이기 위해 Session Layer에 작업하고 싶다.

## 주요 기능

- `Tools/Section` 메뉴로 도구 창 진입
- `Always Display` 기반 창/섹션 표시 정책 제어
- 섹션 매니퓰레이터 표시/숨김 제어
- 빠른 정렬(X/Y/Z), 로컬 축 기준 회전, 컷 방향 반전
- 섹션 prim/variant 생성 및 상태 관리
- viewport별 scene 생성/해제 자동 동기화
- `useSessionLayer` 설정 기반 편집 레이어 선택

## 아키텍처 구성

- `extension.py` (`SectionToolExtension`)
  - 확장 진입점
  - 메뉴 등록, 창 표시 콜백 등록, stage 이벤트 연결
- `ui/section_tool_window.py` (`SectionToolWindow`)
  - 도구 창 수명주기 관리
  - 패널 UI 구성 및 설정 구독
- `tool/section_tool.py` (`SectionTool`)
  - 전역 scene 오케스트레이터(싱글턴)
  - viewport 목록을 감시하며 `SectionScene` 생성/해제
- `tool/section_scene.py` (`SectionScene`)
  - 단일 viewport의 `SceneView + SectionManipulator + SectionModel` 묶음
- `tool/section_model.py` (`SectionModel`)
  - 섹션 transform 추적 및 section plane 계산
  - 계산 결과를 render product prim 속성에 반영
- `common/section_manager.py` (`SectionManager`)
  - section prim/variant 및 transform 속성 관리

## 동작 Flow (상세)

### 1) 확장 시작

1. Kit가 확장을 활성화하면 `SectionToolExtension.on_startup()` 호출
2. `menuPath` 설정을 읽어 `Tools/Section` 메뉴 항목 등록
3. `Workspace.set_show_window_fn()`으로 창 표시 콜백 등록
4. 현재 viewport tool 변경 감시 및 stage opened 이벤트 구독 시작

### 2) 창 열기

1. 사용자가 메뉴에서 Section 창을 열면 `show_window(True)` 실행
2. 최초 호출이면 `SectionToolWindow`를 지연 생성
3. `SectionToolWindow`에서 UI 패널(`OptionsPanel`, `QuickMovePanel`) 빌드
4. 설정 변경 구독(`SETTING_SECTION_ENABLED`, `SETTING_SECTION_MANIPULATOR`, `SETTING_SECTION_DIRECTION`) 시작

### 3) 섹션 활성화

1. 창 표시 또는 설정 변경으로 섹션 활성화 요청 발생
2. `SectionTool.set_visibility(True, ext_id)` 호출
3. 현재 보이는 viewport 목록을 수집해 viewport별 key 생성
4. 없는 key에 대해 `SectionScene` 생성
   - 내부에서 `SectionModel` 생성
   - `SceneView`에 `SectionManipulator` 연결
5. 모든 활성 viewport scene에 frame/show 상태 반영

### 4) 평면 계산 및 렌더 반영

1. `SectionModel`이 현재 section transform(위치/회전)을 읽음
2. 컷 방향 설정(`Top/Bottom`)으로 법선 기준 방향 결정
3. `n·x + d = 0` 형태로 section plane 계수 계산
4. 계산값을 viewport의 render product prim 속성
   (`omni:rtx:scene:sectionPlane:plane`)에 기록

### 5) 사용자 조작

- `QuickMovePanel`
  - X/Y/Z 정렬 버튼 -> `SectionManager.align_widget()`
  - 회전 버튼/각도 -> `SectionManager.rotate_widget()`
  - 컷 방향 반전 -> RTX section 방향 설정 변경
- `SectionManipulator`
  - 호버/클릭 시 선택 레이어 충돌을 줄이기 위한 상태 제어
  - gizmo 표시 시 section widget prim 선택 상태 동기화

### 6) Stage 이벤트 처리

- Stage Opened
  - 기존 섹션 표시 상태 리셋
  - `SectionManager.refresh()` 및 모델 초기화
- Stage Closing
  - 창 숨김 + 섹션 비활성화
  - 설정 구독 정리
- Section 관련 prim 삭제 감지
  - 창/섹션 즉시 비활성화 및 내부 상태 정리

## 멀티뷰포트 처리 방식

- viewport 이름 대신 객체 id 기반 key(`id:<python_id>`)를 사용
- 매 update 이벤트에서 보이는 viewport 목록을 재평가
- 신규 viewport가 생기면 scene 자동 생성
- 닫힌 viewport는 scene 자동 제거
- 섹션 표시 상태는 모든 scene에 동일하게 전파

## 주요 설정

- `exts."morph.hytwin_section".alwaysDisplay`
  - `true`: 창을 닫아도 섹션 유지
  - `false`: 창을 닫으면 섹션 비활성화
- `exts."morph.hytwin_section".useSessionLayer`
  - `true`: Session Layer에 기록(권장)
  - `false`: Root Layer에 기록
- `exts."morph.hytwin_section".menuPath`
  - 메뉴 노출 경로(기본 `Tools/Section`)

## 트러블슈팅 포인트

- 창은 뜨지만 섹션이 안 보임
  - `SETTING_SECTION_ENABLED`, `SETTING_SECTION_MANIPULATOR` 상태 확인
- viewport마다 동작이 다름
  - viewport visibility 상태 및 scene 생성 여부 확인
- stage 전환 후 상태 꼬임
  - stage opened/closing 이벤트에서 refresh/reset 호출되는지 확인
- 데이터가 원본 레이어에 남음
  - `useSessionLayer` 설정이 `true`인지 확인

## 개발 참고

- 코드 루트: `morph/hytwin_section`
- 세부 문서: `docs/Overview.md`, `docs/SETTINGS.md`, `docs/CHANGELOG.md`
