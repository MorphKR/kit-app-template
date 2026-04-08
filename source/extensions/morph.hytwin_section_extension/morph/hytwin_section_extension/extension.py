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

    SETTING_MENU_PATH = "/exts/morph.hytwin_section_extension/menuPath"
    VIEW_TOOLBAR_ID = "section"

    def on_startup(self, ext_id):
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

            self.show_window(None, False)

    def _on_stage_opened(self, stage_event):

        settings = carb.settings.get_settings()
        if settings.get_as_bool(SETTING_SECTION_ENABLED):
            settings.set_bool(SETTING_SECTION_ENABLED, False)
            # OM-79609: Do not make stage dirty
            omni.usd.get_context().set_pending_edit(False)


def get_instance() -> SectionToolExtension:
    return g_singleton
