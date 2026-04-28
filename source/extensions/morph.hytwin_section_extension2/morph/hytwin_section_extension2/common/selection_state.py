# Copyright (c) 2023, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.
#

__all__ = ["SelectionState"]

from typing import Dict

import omni.kit.viewport.utility as vu
from carb.settings import get_settings
from omni.kit.viewport.window import ViewportWindow

CONTEXT_MENU_SETTINGS = "/exts/omni.kit.window.viewport/showContextMenu"

# 참고: 이 처리는 추후 Kit API에서 제공되는 것이 바람직하다. [OM-82367]


class SelectionState:
    def __init__(self, viewport_window: ViewportWindow):
        self.__settings = get_settings()
        self.__layers_state: Dict = {}
        # ViewportWindow 계열이면 선택/컨텍스트 레이어를 직접 제어한다.
        if viewport_window and hasattr(viewport_window, "_find_viewport_layer"):
            self.__layers: Dict = {
                "Selection": viewport_window._find_viewport_layer("Selection", category="manipulator"),
                "ContextMenu": viewport_window._find_viewport_layer("ContextMenu", category="manipulator"),
            }
        else:
            # ViewportWidgetHost는 private layer API가 없으므로 레이어 토글 없이 설정만 제어한다.
            self.__layers = {"Selection": None, "ContextMenu": None}

        ctx_menu_enabled = self.__settings.get(CONTEXT_MENU_SETTINGS)
        self.__ctx_menu_restore = ctx_menu_enabled if ctx_menu_enabled is not None else True

    def destroy(self):
        self.restore()
        for key in self.__layers:
            self.__layers[key] = None

    # TODO: Suspect unused code; remove if so
    @property
    def enabled(self) -> bool:  # pragma: no cover
        sel_layer = self.__layers["Selection"]
        ctx_layer = self.__layers["ContextMenu"]

        if sel_layer and ctx_layer:
            return sel_layer.visible and ctx_layer.visible

        # [VIEW] 컨텍스트 메뉴 레이어가 없는 경우 처리
        if sel_layer is None:
            return False
        return sel_layer.visible

    @enabled.setter
    def enabled(self, value: bool) -> None:
        # 컨텍스트 메뉴 설정과 레이어 가시성을 함께 맞춘다.
        self.__settings.set(CONTEXT_MENU_SETTINGS, value)

        for key in self.__layers:
            item = self.__layers[key]
            if item is not None and hasattr(item, "visible"):
                item.visible = value

    def restore(self):
        """
        Restores the viewport layer states to the original settings.
        """
        self.enabled = True
        # 컨텍스트 메뉴 설정을 원래 값으로 복원
        self.__settings.set(CONTEXT_MENU_SETTINGS, self.__ctx_menu_restore)

    def reserve(self):
        ctx_menu_enabled = self.__settings.get(CONTEXT_MENU_SETTINGS)
        self.__ctx_menu_restore = ctx_menu_enabled if ctx_menu_enabled is not None else True
