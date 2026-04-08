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


# ?뺤옣 吏꾩엯??
# - SectionToolWindow: ?⑤꼸 UI ?섎챸二쇨린 愿由?
# - SectionTool: 酉고룷??湲곗쫰紐????섎챸二쇨린 愿由?
# `extension.toml`??`python.modules`???깅줉??`omni.ext.IExt` ?뚯깮 ?대옒?ㅻ뒗
# ?뺤옣 ?쒖꽦????`on_startup(ext_id)`, 鍮꾪솢?깊솕 ??`on_shutdown()`???몄텧?쒕떎.
class SectionToolExtension(omni.ext.IExt, MenuHelperExtension):
    # ?꾩옱 extension id. ?뺤옣 愿由ъ옄?먯꽌 寃쎈줈/硫뷀??곗씠?곕? 議고쉶?????ъ슜?쒕떎.
    SETTING_MENU_PATH = "/exts/morph.hytwin_section_extension/menuPath"
    VIEW_TOOLBAR_ID = "section"

    def on_startup(self, ext_id):
        self._ext_id = ext_id
        # ?쒖뒪???? QuickLayout)?먯꽌 李??쒖떆瑜??붿껌?????덈룄濡??깅줉???먭퀬,
        # ?ㅼ젣 李?媛앹껜??理쒖큹 ?쒖떆 ?쒖젏??吏???앹꽦?쒕떎.
        self._window = None

        # ?몃?(UI/?덉씠?꾩썐 ?쒖뒪???먯꽌 李??닿린 ?붿껌???ㅼ뼱?????덈룄濡?show 肄쒕갚???깅줉?쒕떎.
        ui.Workspace.set_show_window_fn(WINDOW_NAME, partial(self.show_window, None))
        self._toggle_id = ui.Workspace.set_window_visibility_changed_callback(self._visibility_changed_fn)

        # ?곷떒 硫붾돱??Section ??ぉ???깅줉?쒕떎.
        settings = carb.settings.get_settings()
        self._menu_path = settings.get(SectionToolExtension.SETTING_MENU_PATH)
        menu_name = self._menu_path.split("/")[-1]
        menu_group = "/".join(self._menu_path.split("/")[:-1])
        self.menu_startup(WINDOW_NAME, menu_name, menu_group)
        # ?꾩옱 酉고룷????蹂寃쎌쓣 媛먯떆??Section 李??쒖떆 ?곹깭瑜??숆린?뷀븳??
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

        # SectionTool singleton???↔퀬 ?덈뒗 scene/由ъ냼?ㅻ? ?뺣━?쒕떎.
        SectionTool().destroy()

        settings = carb.settings.get_settings()
        settings.unsubscribe_to_change_events(self._viewport_current_tool_changed_sub)
        self.menu_shutdown()
        # omni.ui???깅줉???덈룄???쒖떆 ?⑥닔瑜??댁젣?쒕떎.
        ui.Workspace.set_show_window_fn(WINDOW_NAME, None)
        ui.Workspace.remove_window_visibility_changed_callback(self._toggle_id)

    def _visibility_changed_fn(self, name: str, visible: bool):
        if name == WINDOW_NAME:
            # ?ъ슜?먭? 李??곗륫 ?곷떒 X 踰꾪듉?쇰줈 ?レ븯?????몄텧?쒕떎.
            self.menu_refresh()

            # OMFP-3552: Section ?쒖꽦 以묒뿉????異⑸룎??以꾩씠湲??꾪빐 ?대퉬寃뚯씠?????꾪솚???쒖뼱?쒕떎.
            settings = carb.settings.get_settings()
            TOOL_NAME = WINDOW_NAME
            if visible:
                # Measure 媛숈? ?ㅻⅨ ?댁쓣 媛뺤젣濡??꾩? ?딅룄濡?navigation ?곹깭?먯꽌留??꾪솚?쒕떎.
                if settings.get_as_string(CURRENT_TOOL_PATH) == "navigation":
                    settings.set_string(CURRENT_TOOL_PATH, TOOL_NAME)
            elif settings.get_as_string(CURRENT_TOOL_PATH) == TOOL_NAME:
                settings.set_string(CURRENT_TOOL_PATH, "navigation")

    def show_window(self, menu, value):
        # value=True硫?李쎌쓣 ?앹꽦/?쒖떆, False硫??대? ?앹꽦??李쎈쭔 ?④릿??
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
            # "none"? 紐⑤뱺 ?꾧뎄 鍮꾪솢???곹깭?대?濡?李쎈룄 ?④퍡 ?④릿??
            self.show_window(None, False)

    def _on_stage_opened(self, stage_event):
        # ???ㅽ뀒?댁?媛 ?대━硫??뱀뀡 ?곹깭瑜?珥덇린?뷀빐 ?댁쟾 ???곹깭媛
        # ?ㅼ쓬 ?몄뀡?쇰줈 ?욎뿬 ?ㅼ뼱媛吏 ?딅룄濡??쒕떎.
        settings = carb.settings.get_settings()
        if settings.get_as_bool(SETTING_SECTION_ENABLED):
            settings.set_bool(SETTING_SECTION_ENABLED, False)
            # OM-79609: Do not make stage dirty
            omni.usd.get_context().set_pending_edit(False)


def get_instance() -> SectionToolExtension:
    """`morph.hytwin_section_extension` ?뺤옣???깃????몄뒪?댁뒪瑜?諛섑솚?쒕떎.

    Returns:
        SectionToolExtension: ?ъ슜 媛?ν븯硫??몄뒪?댁뒪, ?놁쑝硫?None.
    """
    return g_singleton

