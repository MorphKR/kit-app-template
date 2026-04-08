```{csv-table}
**Extension**: {{ extension_version }},**Documentation Generated**: {sub-ref}`today`
```

# 설정

## 확장에서 제공하는 설정

### exts."morph.hytwin_section_extension".menuPath
- **기본값**: `Tools/Section`
- **설명**: Section Tool 창이 등록될 메뉴 경로를 지정합니다.

### exts."morph.hytwin_section_extension".useSessionLayer
- **기본값**: `True`
- **설명**: 섹션 편집 내용을 USD Session Layer에 기록할지 여부를 설정합니다.

### exts."morph.hytwin_section_extension".alwaysDisplay
- **기본값**: `False`
- **설명**: UI 창 표시 상태와 무관하게 섹션을 항상 표시할지 제어합니다.

## 확장에서 사용하며 다른 확장이 제공하는 설정

### CURRENT_TOOL_PATH
- **설명**: 현재 활성 도구 경로를 읽어 창 표시/숨김 또는 도구 전환 제어에 사용합니다.

### SETTING_SECTION_ENABLED
- **설명**: RTX 섹션 기능 활성화 여부를 나타냅니다.

### SETTING_SECTION_LIGHT
- **설명**: 섹션 조명 사용 여부를 제어합니다.

### SETTING_SECTION_DIRECTION
- **설명**: 절단 방향(Top/Bottom) 값을 지정합니다.

### SETTING_SECTION_PLANE
- **설명**: 섹션 평면 방정식 값(nx, ny, nz, d)을 저장하는 경로입니다.

### SETTING_SECTION_MANIPULATOR
- **설명**: 섹션 조작기(Manipulator) 표시 여부를 제어합니다.

### SETTING_RTX_DEFAULT_SECTION_DIRECTION
- **설명**: RTX 기본 절단 방향 설정값입니다.

### SETTING_RTX_DEFAULT_SECTION_MANIPULATOR
- **설명**: RTX 기본 조작기 표시 설정값입니다.

### /exts/omni.kit.window.viewport/showContextMenu
- **설명**: 뷰포트 컨텍스트 메뉴 표시 상태를 제어합니다.

### /app/transform/operation
- **설명**: 현재 변환 모드(예: `move`)를 나타냅니다.

### SETTING_SECTION_ALWAYS_DISPLAY
- **설명**: 섹션 UI의 상시 표시 동작과 연동되는 설정입니다.
