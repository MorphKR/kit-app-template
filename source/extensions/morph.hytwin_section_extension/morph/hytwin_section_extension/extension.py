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



class SectionToolExtension(omni.ext.IExt, MenuHelperExtension):

    """이 모듈의 주요 기능을 구성하는 클래스다."""
    SETTING_MENU_PATH = "/exts/morph.hytwin_section_extension/menuPath"
    VIEW_TOOLBAR_ID = "section"

    def on_startup(self, ext_id):
        """이벤트가 발생했을 때 후속 처리를 수행한다."""
        self._ext_id = ext_id

        self._window = None


        ui.Workspace.set_show_window_fn(WINDOW_NAME, partial(self.show_window, None))
        self._toggle_id = ui.Workspace.set_window_visibility_changed_callback(self._visibility_changed_fn)


        settings = carb.settings.get_settings()
        self._menu_path = settings.get(SectionToolExtension.SETTING_MENU_PATH)
        menu_name = self._menu_path.split("/")[-1]
        menu_group = "/".join(self._menu_path.split("/")[:-1])
        self.menu_startup(WINDOW_NAME, menu_name, menu_group)

        self._viewport_current_tool_changed_sub = settings.subscribe_to_node_change_events(
            CURRENT_TOOL_PATH, self._on_view_current_tool_changed
        )

        self._stage_sub = get_eventdispatcher().observe_event(
            observer_name="morph.hytwin_section_extension.startup",
            event_name=omni.usd.get_context().stage_event_name(omni.usd.StageEventType.OPENED),
            on_event=self._on_stage_opened,
        )

        global g_singleton
        g_singleton = self

    def on_shutdown(self):
        """이벤트가 발생했을 때 후속 처리를 수행한다."""
        global g_singleton
        g_singleton = None

        self._stage_sub = None
        if self._window:
            self._window.destroy()
            self._window = None

        SectionTool().destroy()

        settings = carb.settings.get_settings()
        settings.unsubscribe_to_change_events(self._viewport_current_tool_changed_sub)
        self.menu_shutdown()

        ui.Workspace.set_show_window_fn(WINDOW_NAME, None)
        ui.Workspace.remove_window_visibility_changed_callback(self._toggle_id)

    def _visibility_changed_fn(self, name: str, visible: bool):
        """해당 함수의 핵심 로직을 수행한다."""
        if name == WINDOW_NAME:

            self.menu_refresh()


            settings = carb.settings.get_settings()
            TOOL_NAME = WINDOW_NAME
            if visible:

                if settings.get_as_string(CURRENT_TOOL_PATH) == "navigation":
                    settings.set_string(CURRENT_TOOL_PATH, TOOL_NAME)
            elif settings.get_as_string(CURRENT_TOOL_PATH) == TOOL_NAME:
                settings.set_string(CURRENT_TOOL_PATH, "navigation")

    def show_window(self, menu, value):

        """표시 상태를 변경하고 연관 상태를 동기화한다."""
        if value:
            if not self._window:
                self._window = SectionToolWindow(WINDOW_NAME, self._ext_id)
            else:
                self._window.show(True)
        elif self._window:
            self._window.show(False)

    def _on_view_current_tool_changed(self, item, *_):
        """이벤트가 발생했을 때 후속 처리를 수행한다."""
        current_tool = carb.dictionary.get_dictionary().get(item)
        visible = current_tool == SectionToolExtension.VIEW_TOOLBAR_ID
        if visible:
            self.show_window(None, visible)
        elif current_tool is None or str(current_tool).lower() == "none":

            self.show_window(None, False)

    def _on_stage_opened(self, stage_event):

        """이벤트가 발생했을 때 후속 처리를 수행한다."""
        settings = carb.settings.get_settings()
        if settings.get_as_bool(SETTING_SECTION_ENABLED):
            settings.set_bool(SETTING_SECTION_ENABLED, False)
            # OM-79609: Do not make stage dirty
            omni.usd.get_context().set_pending_edit(False)


def get_instance() -> SectionToolExtension:
    """현재 상태에서 필요한 값을 조회해 반환한다."""
    return g_singleton
