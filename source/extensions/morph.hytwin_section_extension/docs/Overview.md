```{csv-table}
**Extension**: {{ extension_version }},**Documentation Generated**: {sub-ref}`today`
```

# 개요

**morph.hytwin_section_extension**은 Omniverse Kit 뷰포트에서 섹션(절단 평면)을 생성하고 조작하는 확장입니다.  
사용자는 전용 UI와 뷰포트 Manipulator를 통해 섹션 정렬, 회전, 위치 이동, 절단 방향 전환을 수행할 수 있습니다.

```{image} ../../../../source/extensions/ui/morph.hytwin_section_extension/data/icons/preview.png
---
align: center
---
```

## UI 구성 요소

- **Section Tool Window**
  - 섹션 기능을 제어하는 메인 창입니다.
- **Options Panel**
  - 섹션 활성화, 표시 상태, 기본 옵션을 제어합니다.
- **Quick Move Panel**
  - X/Y/Z 정렬, 회전, Prim 경로 기반 이동 기능을 제공합니다.
- **Section Manipulator**
  - 뷰포트 상에서 섹션 평면을 직접 선택하고 조작할 수 있는 인터랙션 컴포넌트입니다.

## 사용 흐름

1. `Tools/Section` 메뉴에서 창을 엽니다.
2. 섹션 기능을 활성화하면 섹션 오브젝트와 viewport scene이 준비됩니다.
3. Quick Move/Manipulator를 통해 섹션을 조작합니다.
4. 설정 변경은 즉시 렌더 결과(절단 평면)에 반영됩니다.

## 동작 특성

- 섹션 기능 실행과 UI 표시가 분리되어 있습니다.
  - UI 경로: `SectionToolWindow`가 `SectionManager.run_section_runtime(...)` 호출
  - 비UI 경로: `SectionManager.run_section_only()` / `stop_section_only()`
- 멀티 뷰포트 환경에서 뷰포트별 `Section_Tool_Object`를 관리합니다.
- `useSessionLayer` 설정에 따라 Session Layer 또는 Root Layer에 편집 내용을 기록합니다.
