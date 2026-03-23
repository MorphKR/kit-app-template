# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

"""
아웃라인 설정 창 모듈

Hover 아웃라인 색상/두께 설정 UI 창을 생성하고, 메뉴 항목을 등록합니다.
"""

from typing import Callable, Optional

import omni.ui as ui
from omni.kit.menu.utils import add_menu_items, remove_menu_items, MenuItemDescription

from .outline_settings_ui import build_outline_settings_ui


# -----------------------------------------------------------------------------
# 상수
# -----------------------------------------------------------------------------
WINDOW_TITLE = "Raycast Outline"
MENU_PATH = "Window"
WINDOW_WIDTH = 320
WINDOW_HEIGHT = 220


class OutlineSettingsWindowManager:
    """
    아웃라인 설정 창 및 메뉴를 관리하는 클래스.

    Window 메뉴에 "Raycast Outline 설정" 항목을 추가하고,
    클릭 시 설정 창을 표시합니다.
    """

    def __init__(self, on_settings_changed: Optional[Callable[[], None]] = None):
        """
        Args:
            on_settings_changed: 색상/두께 변경 시 호출할 콜백 (예: 아웃라인 리빌드)
        """
        self._on_settings_changed = on_settings_changed
        self._window: Optional[ui.Window] = None
        self._menu_items = []

    def build(self) -> None:
        """설정 창을 생성하고 메뉴 항목을 등록합니다."""
        self._window = ui.Window(
            WINDOW_TITLE,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            visible=False,
        )

        build_outline_settings_ui(self._window, on_settings_changed=self._on_settings_changed)

        self._menu_items = [
            MenuItemDescription(
                name="Raycast Outline 설정",
                onclick_fn=self.show,
            )
        ]
        add_menu_items(self._menu_items, MENU_PATH)

    def destroy(self) -> None:
        """설정 창을 닫고 메뉴 항목을 제거합니다."""
        if self._window:
            self._window.destroy()
            self._window = None
        if self._menu_items:
            remove_menu_items(self._menu_items, MENU_PATH)
            self._menu_items = []

    def show(self) -> None:
        """설정 창을 표시하고 포커스를 줍니다."""
        if self._window:
            self._window.visible = True
            self._window.focus()
