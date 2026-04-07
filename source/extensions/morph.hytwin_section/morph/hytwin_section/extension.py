# Copyright (c) 2022, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.
#
from functools import partial

import carb.dictionary
import carb.settings
import omni.ext
import omni.ui as ui
import omni.usd
from carb.eventdispatcher import get_eventdispatcher
from omni.kit.menu.utils import MenuHelperExtension

from .common import CURRENT_TOOL_PATH, SETTING_SECTION_ENABLED, WINDOW_NAME
from .tool import SectionTool
from .ui import SectionToolWindow

g_singleton = None


# 확장 진입점:
# - SectionToolWindow: 패널 UI 수명주기 관리
# - SectionTool: 뷰포트 기즈모/씬 수명주기 관리
# `extension.toml`의 `python.modules`에 등록된 `omni.ext.IExt` 파생 클래스는
# 확장 활성화 시 `on_startup(ext_id)`, 비활성화 시 `on_shutdown()`이 호출된다.
class SectionToolExtension(omni.ext.IExt, MenuHelperExtension):
    # 현재 extension id. 확장 관리자에서 경로/메타데이터를 조회할 때 사용한다.
    SETTING_MENU_PATH = "/exts/morph.hytwin_section/menuPath"
    VIEW_TOOLBAR_ID = "section"

    def on_startup(self, ext_id):
        self._ext_id = ext_id
        # 시스템(예: QuickLayout)에서 창 표시를 요청할 수 있도록 등록해 두고,
        # 실제 창 객체는 최초 표시 시점에 지연 생성한다.
        self._window = None

        # 외부(UI/레이아웃 시스템)에서 창 열기 요청이 들어올 수 있도록 show 콜백을 등록한다.
        ui.Workspace.set_show_window_fn(WINDOW_NAME, partial(self.show_window, None))
        self._toggle_id = ui.Workspace.set_window_visibility_changed_callback(self._visibility_changed_fn)

        # 상단 메뉴에 Section 항목을 등록한다.
        settings = carb.settings.get_settings()
        self._menu_path = settings.get(SectionToolExtension.SETTING_MENU_PATH)
        menu_name = self._menu_path.split("/")[-1]
        menu_group = "/".join(self._menu_path.split("/")[:-1])
        self.menu_startup(WINDOW_NAME, menu_name, menu_group)
        # 현재 뷰포트 툴 변경을 감시해 Section 창 표시 상태를 동기화한다.
        self._viewport_current_tool_changed_sub = settings.subscribe_to_node_change_events(
            CURRENT_TOOL_PATH, self._on_view_current_tool_changed
        )

        self._stage_sub = get_eventdispatcher().observe_event(
            observer_name="morph.hytwin_section.startup",
            event_name=omni.usd.get_context().stage_event_name(omni.usd.StageEventType.OPENED),
            on_event=self._on_stage_opened,
        )

        global g_singleton
        g_singleton = self

    def on_shutdown(self):
        global g_singleton
        g_singleton = None

        self._stage_sub = None
        if self._window:
            self._window.destroy()
            self._window = None

        # SectionTool singleton이 잡고 있는 scene/리소스를 정리한다.
        SectionTool().destroy()

        settings = carb.settings.get_settings()
        settings.unsubscribe_to_change_events(self._viewport_current_tool_changed_sub)
        self.menu_shutdown()
        # omni.ui에 등록한 윈도우 표시 함수를 해제한다.
        ui.Workspace.set_show_window_fn(WINDOW_NAME, None)
        ui.Workspace.remove_window_visibility_changed_callback(self._toggle_id)

    def _visibility_changed_fn(self, name: str, visible: bool):
        if name == WINDOW_NAME:
            # 사용자가 창 우측 상단 X 버튼으로 닫았을 때 호출된다.
            self.menu_refresh()

            # OMFP-3552: Section 활성 중에는 툴 충돌을 줄이기 위해 내비게이션 툴 전환을 제어한다.
            settings = carb.settings.get_settings()
            TOOL_NAME = WINDOW_NAME
            if visible:
                # Measure 같은 다른 툴을 강제로 끄지 않도록 navigation 상태에서만 전환한다.
                if settings.get_as_string(CURRENT_TOOL_PATH) == "navigation":
                    settings.set_string(CURRENT_TOOL_PATH, TOOL_NAME)
            elif settings.get_as_string(CURRENT_TOOL_PATH) == TOOL_NAME:
                settings.set_string(CURRENT_TOOL_PATH, "navigation")

    def show_window(self, menu, value):
        # value=True면 창을 생성/표시, False면 이미 생성된 창만 숨긴다.
        if value:
            if not self._window:
                self._window = SectionToolWindow(WINDOW_NAME, self._ext_id)
            else:
                self._window.show(True)
        elif self._window:
            self._window.show(False)

    def _on_view_current_tool_changed(self, item, *_):
        current_tool = carb.dictionary.get_dictionary().get(item)
        visible = current_tool == SectionToolExtension.VIEW_TOOLBAR_ID
        if visible:
            self.show_window(None, visible)
        elif current_tool is None or str(current_tool).lower() == "none":
            # "none"은 모든 도구 비활성 상태이므로 창도 함께 숨긴다.
            self.show_window(None, False)

    def _on_stage_opened(self, stage_event):
        # 새 스테이지가 열리면 섹션 상태를 초기화해 이전 씬 상태가
        # 다음 세션으로 섞여 들어가지 않도록 한다.
        settings = carb.settings.get_settings()
        if settings.get_as_bool(SETTING_SECTION_ENABLED):
            settings.set_bool(SETTING_SECTION_ENABLED, False)
            # OM-79609: Do not make stage dirty
            omni.usd.get_context().set_pending_edit(False)


def get_instance() -> SectionToolExtension:
    """`morph.hytwin_section` 확장의 싱글턴 인스턴스를 반환한다.

    Returns:
        SectionToolExtension: 사용 가능하면 인스턴스, 없으면 None.
    """
    return g_singleton
