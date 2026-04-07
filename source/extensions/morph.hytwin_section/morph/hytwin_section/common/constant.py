from pathlib import Path

# 확장/렌더러 설정 경로 상수
PERSISTENT_SETTINGS_PREFIX = "/persistent"
SETTING_SECTION_TOOL_ROOT = "/exts/morph.hytwin_section/"
SETTING_SECTION_ALWAYS_DISPLAY = SETTING_SECTION_TOOL_ROOT + "alwaysDisplay"
SETTING_SECTION_USE_SESSION_LAYER = SETTING_SECTION_TOOL_ROOT + "useSessionLayer"

SETTING_SECTION_MANIPULATOR = "/rtx/sectionPlane/manipulator"
SETTING_SECTION_ENABLED = "/rtx/sectionPlane/enabled"
SETTING_SECTION_LIGHT = "/rtx/sectionPlane/sectionLight"
SETTING_SECTION_PLANE = "/rtx/sectionPlane/plane"
SETTING_SECTION_DIRECTION = "/rtx/sectionPlane/cutDirection"
SETTING_RTX_DEFAULT_SECTION_DIRECTION = "/rtx-defaults/sectionPlane/cutDirection"
SETTING_RTX_DEFAULT_SECTION_MANIPULATOR = "/rtx-defaults/sectionPlane/manipulator"
TRANSFORM_OP_SETTING = "/app/transform/operation"
VIEWPORT_APERTURE_COMFORM_POLICY = "/app/hydra/aperture/conform"
CURRENT_TOOL_PATH = "/app/viewport/currentTool"
WINDOW_NAME = "Section"

# 기본 컷 방향(Top=true)
DEFAULT_SECTION_TOP = True

# Stage 창에서 섹션 보조 prim을 숨기기 위한 메타데이터 키
HIDE_IN_STAGE_WINDOW = "hide_in_stage_window"
# UI/씬 렌더링에 사용하는 공통 색상 값
SECTION_COLOR = 0xFFD9A223
SECTION_HOVER = 0xFFD9A243
# RTX cutDirection 설정에서 Top 방향을 의미하는 값
SECTION_DIRECTION_TOP = 1
