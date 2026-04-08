# Section Tool (`morph.hytwin_section_extension`)

`morph.hytwin_section_extension`은 Omniverse Kit 뷰포트에서 섹션(절단 평면)을 생성/정렬/회전/이동할 수 있는 확장입니다.  
UI 창을 통해 조작할 수도 있고, Python API로 UI 없이 섹션 기능만 실행할 수도 있습니다.

## 주요 기능
- `Tools/Section` 메뉴에서 Section Tool 창 실행
- 섹션 평면 정렬(X/Y/Z), 회전, 절단 방향 반전
- Prim 경로 기준 섹션 위치 이동
- 멀티 뷰포트 환경에서 뷰포트별 섹션 객체(`Section_Tool_Object`) 관리
- Session Layer 기반 편집 지원(`useSessionLayer`)

## 아키텍처 개요
- `extension.py`
  - 확장 시작/종료, 메뉴 등록, 창 표시 콜백 처리
- `ui/section_tool_window.py`
  - Section Tool 메인 창
  - 창 활성화 시 `SectionManager.run_section_runtime()` 호출
- `common/section_manager.py`
  - 섹션 prim/variant/transform 관리
  - UI와 분리된 런타임 실행 함수 제공
- `tool/section_tool.py`
  - 뷰포트 scene 동기화 및 표시 제어
- `tool/section_scene.py`, `tool/section_model.py`, `tool/section_manipulator.py`
  - viewport별 SceneView/모델/조작기 처리

## UI 실행과 기능 실행 분리
현재 구현은 다음처럼 분리되어 있습니다.
- `SectionManager.set_section_enabled()`:
  - 섹션 설정값만 On/Off (UI 창 제어 안 함)
- `SectionToolWindow`:
  - UI가 열릴 때 `SectionManager.run_section_runtime(...)`로 기능 실행

즉, UI 경로와 기능 경로를 분리해 사용할 수 있습니다.

## Python API (UI 없이 사용)
아래 코드는 Script Editor에서 직접 실행할 수 있습니다.

```python
from morph.hytwin_section_extension.common import SectionManager

# 섹션 기능만 실행(UI 창 없음)
SectionManager().run_section_only()

# 섹션 기능만 중지(UI 창 없음)
SectionManager().stop_section_only()
```

필요 시 gizmo까지 같이 활성화:

```python
from morph.hytwin_section_extension.common import SectionManager

SectionManager().run_section_runtime(show_gizmo=True)
```

## 주요 설정
- `exts."morph.hytwin_section_extension".alwaysDisplay`
  - `true`: 창을 닫아도 섹션 표시 유지
  - `false`: 창 닫힘에 따라 섹션 표시 해제
- `exts."morph.hytwin_section_extension".useSessionLayer`
  - `true`: Session Layer에 편집 기록
  - `false`: Root Layer에 편집 기록
- `exts."morph.hytwin_section_extension".menuPath`
  - 기본값: `Tools/Section`

## 트러블슈팅
- `ImportError` / `NameError` 발생 시
  - 확장이 활성화되어 있는지 확인
  - import 경로 확인:
    - `from morph.hytwin_section_extension.common import SectionManager`
- 섹션이 보이지 않을 때
  - `SETTING_SECTION_ENABLED`, `SETTING_SECTION_MANIPULATOR` 상태 확인
  - stage 변경 직후라면 한두 프레임 뒤 재시도

## 관련 문서
- `docs/Overview.md`
- `docs/SETTINGS.md`
- `docs/CHANGELOG.md`
