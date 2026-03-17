# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

"""
Raycast Outline Extension - 진입점

마우스 hover 시 뷰포트에서 raycast를 수행하고, prim 위에 Hover 아웃라인을 표시합니다.
클릭 시 USD 선택에 추가되며, Hover 아웃라인은 선택 시스템과 독립적으로 동작합니다.

모듈 구조:
- extension.py: 확장 진입점 (본 파일)
- ui/: 설정 창, UI 빌더, 색상/두께 데이터
- events/: raycast, Hover/Click 이벤트
- actions/: 아웃라인 overlay, 그리기 (Manipulator, Model)
"""

import omni.ext
from typing import Optional

# 1. 이벤트 모듈 (독립 - overlay/USD에 종속 없음)
from .events.viewport_raycast_events import ViewportEventManager
# 2. overlay 모듈 (이벤트에 연결될 동작)
from .actions.outline_overlay import OutlineOverlay
from .ui.outline_settings_window import OutlineSettingsWindowManager


class RaycastOutlineExtension(omni.ext.IExt):
    """
    Raycast Outline 확장 메인 클래스.

    on_startup에서 ViewportRaycastOverlay와 SettingsWindowManager를 생성하고,
    on_shutdown에서 리소스를 정리합니다.
    """

    def on_startup(self, ext_id: str) -> None:
        """확장 활성화 시 호출됩니다."""
        print("[moprh.raycast_outline] Extension startup")


        self._ext_id = ext_id
        self._overlay: Optional[OutlineOverlay] = None
        self._settings_manager: Optional[OutlineSettingsWindowManager] = None

        # 1. 이벤트 매니저 생성 (events 모듈 - 독립)
        self._overlay = OutlineOverlay(ext_id)
        event_manager = ViewportEventManager(self._overlay)

        # 2. overlay가 자기 핸들러 등록 (overlay → events 연동)
        self._overlay.register_handlers(event_manager)

        # 3. overlay 설정 (뷰포트에 SceneView 추가)
        self._overlay.setup(event_manager=event_manager)

        # 4. 설정 창 및 메뉴 (Window > Raycast Outline 설정)
        def on_settings_changed():
            """설정 변경 시 아웃라인 리빌드."""
            if self._overlay:
                self._overlay.invalidate_outline()

        self._settings_manager = OutlineSettingsWindowManager(on_settings_changed=on_settings_changed)
        self._settings_manager.build()

    def on_shutdown(self) -> None:
        """확장 비활성화 시 리소스를 정리합니다."""
        print("[moprh.raycast_outline] Extension shutdown")

        if self._settings_manager:
            self._settings_manager.destroy()
            self._settings_manager = None

        if self._overlay:
            self._overlay.destroy()
            self._overlay = None
