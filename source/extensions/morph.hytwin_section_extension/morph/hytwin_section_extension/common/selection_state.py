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

from carb.settings import get_settings
from omni.kit.viewport.window import ViewportWindow

CONTEXT_MENU_SETTINGS = "/exts/omni.kit.window.viewport/showContextMenu"


class SelectionState:
    """선택/컨텍스트 메뉴 레이어 표시 상태를 임시 제어한다."""

    def __init__(self, viewport_window: ViewportWindow):
        """viewport 레이어 참조와 복구 상태를 초기화한다."""
        self.__settings = get_settings()
        self.__layers_state: Dict = {}
        if viewport_window and hasattr(viewport_window, "_find_viewport_layer"):
            self.__layers: Dict = {
                "Selection": viewport_window._find_viewport_layer("Selection", category="manipulator"),
                "ContextMenu": viewport_window._find_viewport_layer("ContextMenu", category="manipulator"),
            }
        else:
            self.__layers = {"Selection": None, "ContextMenu": None}

        ctx_menu_enabled = self.__settings.get(CONTEXT_MENU_SETTINGS)
        self.__ctx_menu_restore = ctx_menu_enabled if ctx_menu_enabled is not None else True

    def destroy(self):
        """상태를 복구하고 내부 참조를 해제한다."""
        self.restore()
        for key in self.__layers:
            self.__layers[key] = None

    # TODO: Suspect unused code; remove if so
    @property
    def enabled(self) -> bool:  # pragma: no cover
        """선택/컨텍스트 메뉴 레이어 활성 여부를 반환한다."""
        sel_layer = self.__layers["Selection"]
        ctx_layer = self.__layers["ContextMenu"]

        if sel_layer and ctx_layer:
            return sel_layer.visible and ctx_layer.visible

        if sel_layer is None:
            return False
        return sel_layer.visible

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """선택/컨텍스트 메뉴 관련 레이어 표시 상태를 설정한다."""
        self.__settings.set(CONTEXT_MENU_SETTINGS, value)

        for key in self.__layers:
            item = self.__layers[key]
            if item is not None and hasattr(item, "visible"):
                item.visible = value

    def restore(self):
        """이전에 저장한 컨텍스트 메뉴 설정으로 복구한다."""
        self.enabled = True
        self.__settings.set(CONTEXT_MENU_SETTINGS, self.__ctx_menu_restore)

    def reserve(self):
        """현재 컨텍스트 메뉴 설정을 복구용으로 저장한다."""
        ctx_menu_enabled = self.__settings.get(CONTEXT_MENU_SETTINGS)
        self.__ctx_menu_restore = ctx_menu_enabled if ctx_menu_enabled is not None else True
