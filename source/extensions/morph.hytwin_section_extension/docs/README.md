# Section Tool (`morph.hytwin_section_extension`)

`morph.hytwin_section_extension`은 Omniverse Kit에서 섹션(절단 평면) 기능을 제공하는 확장입니다.
이 확장은 UI 기반 조작과 스크립트 기반 자동 실행을 모두 지원하며, 멀티 뷰포트 환경에서도 안정적으로 동작하도록 구성되어 있습니다.

## 1. 개발 목적

- 모델 내부를 빠르게 확인하기 위한 절단 평면 생성/조작
- 섹션 오브젝트의 정렬, 회전, 위치 이동 기능을 단순한 UI로 제공
- Python API를 통한 비UI 실행 자동화 지원

## 2. 주요 기능

- `Tools/Section` 메뉴에서 Section Tool 창 실행
- 섹션 활성화/비활성화
- X/Y/Z 축 정렬
- 로컬 축 기반 회전(각도 선택)
- 절단 방향 반전(Top/Bottom)
- Prim 경로 기준 섹션 위치 이동
- 섹션 대상(`Section_Tool_Object`) 선택 리스트 제공
- Session Layer 기반 편집 지원

## 3. 모듈 구성

- `extension.py`
  - 확장 시작/종료, 메뉴 등록, 창 표시 콜백 처리
- `ui/section_tool_window.py`
  - 메인 창 구성 및 표시 상태에 따른 런타임 실행 제어
- `ui/options_panel.py`, `ui/quick_move_panel.py`
  - 옵션/빠른 이동/회전 UI
- `common/section_manager.py`
  - 섹션 prim/variant/transform/속성 관리
  - UI와 분리된 실행 함수 제공
- `tool/section_tool.py`
  - viewport scene lifecycle 관리
- `tool/section_scene.py`
  - viewport별 SceneView + Manipulator + Model 연결
- `tool/section_model.py`
  - transform 추적 및 section plane 계산/반영
- `tool/section_manipulator.py`
  - 뷰포트 인터랙션(클릭/호버/선택) 처리

## 4. 실행 흐름

### 4.1 UI 경로

1. `Tools/Section` 메뉴로 창 열기
2. `SectionToolWindow` 활성화
3. `SectionManager.run_section_runtime(...)` 호출
4. 섹션 오브젝트 준비 + viewport scene 표시 + 필요 시 gizmo 표시

### 4.2 비UI 경로(스크립트)

1. `SectionManager` import
2. `run_section_only()`로 기능만 실행
3. 필요 시 `stop_section_only()`로 기능 중지

## 5. Python API 예제

```python
from morph.hytwin_section_extension.common import SectionManager

# 기능만 실행(UI 창 없음)
SectionManager().run_section_only()

# 기능만 중지(UI 창 없음)
SectionManager().stop_section_only()
```

```python
from morph.hytwin_section_extension.common import SectionManager

# gizmo까지 포함하여 런타임 실행
SectionManager().run_section_runtime(show_gizmo=True)
```

## 6. 주요 설정

- `exts."morph.hytwin_section_extension".menuPath`
  - 메뉴 경로 설정 (기본: `Tools/Section`)
- `exts."morph.hytwin_section_extension".alwaysDisplay`
  - 창을 닫아도 섹션 표시 유지 여부
- `exts."morph.hytwin_section_extension".useSessionLayer`
  - Session Layer 기록 여부

추가 설정 상세는 `docs/SETTINGS.md`를 참고하세요.

## 7. 최근 변경 사항 (현재 코드 기준)

- 섹션 기능 실행(`SectionManager`)과 UI 표시(`SectionToolWindow`) 분리
- `run_section_runtime()` / `run_section_only()` / `stop_section_only()` 제공
- 선택된 `Section_Tool_Object` 기준으로 정렬/회전/이동 적용

## 8. 트러블슈팅

- `ImportError: cannot import name 'SectionManager'`
  - extension 활성화 여부 확인
  - import 경로 확인:
    - `from morph.hytwin_section_extension.common import SectionManager`
- UI 없이 실행했는데 창이 뜨는 문제
  - `run_section_only()` 사용
  - `run_section_runtime()`는 파라미터에 따라 gizmo 표시가 동반될 수 있음
- 섹션이 보이지 않는 문제
  - `SETTING_SECTION_ENABLED`, `SETTING_SECTION_MANIPULATOR` 상태 점검
  - stage 전환 직후에는 1~2 프레임 대기 후 확인

## 9. 관련 문서

- `docs/Overview.md`
- `docs/SETTINGS.md`
- `docs/CHANGELOG.md`
