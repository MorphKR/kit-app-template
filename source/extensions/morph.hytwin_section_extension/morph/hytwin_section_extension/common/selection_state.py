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



class SelectionState:
    def __init__(self, viewport_window: ViewportWindow):
        self.__settings = get_settings()
        self.__layers_state: Dict = {}
        self.__layers: Dict = {
            "Selection": viewport_window._find_viewport_layer("Selection", category="manipulator"),
            "ContextMenu": viewport_window._find_viewport_layer("ContextMenu", category="manipulator"),
        }

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

        if sel_layer is None:
            return False
        return sel_layer.visible

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self.__settings.set(CONTEXT_MENU_SETTINGS, value)

        for key in self.__layers:
            item = self.__layers[key]
            if item is not None and hasattr(item, "visible"):
                item.visible = value

    def restore(self):
        """
        酉고룷???덉씠?댁? 而⑦뀓?ㅽ듃 硫붾돱 ?ㅼ젙??珥덇린 ?곹깭濡?蹂듦뎄?쒕떎.
        """
        self.enabled = True
        self.__settings.set(CONTEXT_MENU_SETTINGS, self.__ctx_menu_restore)

    def reserve(self):
        ctx_menu_enabled = self.__settings.get(CONTEXT_MENU_SETTINGS)
        self.__ctx_menu_restore = ctx_menu_enabled if ctx_menu_enabled is not None else True
