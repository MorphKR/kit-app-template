# Copyright (c) 2018-2020, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.
#
__all__ = ["SectionScene"]

import carb.settings
import omni.kit.app
import omni.ui as ui
from omni.kit.viewport.utility import get_active_viewport_window
from omni.ui import scene as sc

from ..common import (
    SECTION_COLOR,
    SECTION_DIRECTION_TOP,
    SECTION_HOVER,
    SETTING_SECTION_DIRECTION,
    SETTING_SECTION_ENABLED,
    SectionManager,
    get_data_path,
)
from .section_manipulator import SectionManipulator
from .section_model import SectionModel

ICON_SIZE = 32
ICON_OFFSET = 100


class SectionScene:

    """뷰포트에서 SceneView, 모델, 매니퓰레이터 연결을 관리한다."""
    def __init__(self, ext_id: str, viewport_window=None, viewport_key: str = None, **kwargs):
        """인스턴스의 초기 상태를 구성한다."""
        self._ext_id = ext_id
        self._settings = carb.settings.get_settings()
        self._section_model = None
        self._manipulator = None
        self._viewport_window = viewport_window or get_active_viewport_window()
        self._viewport_key = viewport_key
        self.detachable = False
        self._scene_view = None

        self._cut_direction_setting_tp = omni.kit.app.SettingChangeSubscription(
            SETTING_SECTION_DIRECTION, lambda *_: self._on_section_direction_changed()
        )
        self._section_model = SectionModel(viewport_key=self._viewport_key, viewport_window=self._viewport_window)

        self.__build_window()

    @property
    def viewport_api(self):
        """현재 상태에서 필요한 값을 조회해 반환한다."""
        return self._viewport_window.viewport_api if self._viewport_window else None

    @property
    def viewport_window(self):
        """현재 상태에서 필요한 값을 조회해 반환한다."""
        return self._viewport_window

    def destroy(self):
        """사용한 구독과 리소스를 정리한다."""
        if self._manipulator:
            self._manipulator.destroy()
            self._manipulator = None
        if self._section_model:
            self._section_model.destroy()
            self._section_model = None

        self._settings = None
        self._cut_direction_setting_tp = None

        if self._viewport_window and self._scene_view:
            self._viewport_window.viewport_api.remove_scene_view(self._scene_view)

        if self._scene_view:
            self._scene_view.destroy()
            self._scene_view = None

        self._viewport_window = None

    def __build_window(self):
        """UI 위젯 트리를 구성한다."""
        if not self._viewport_window:
            return
        self.frame = self._viewport_window.get_frame(self._ext_id)
        with self.frame:
            self._scene_view = sc.SceneView()
            with self._scene_view.scene:
                self._manipulator = SectionManipulator(
                    model=self._section_model, viewport_window=self._viewport_window, viewport_key=self._viewport_key
                )

            self._viewport_window.viewport_api.add_scene_view(self._scene_view)

    def show(self, visible: bool):
        """표시 상태를 변경하고 연관 상태를 동기화한다."""
        if not hasattr(self, "frame") or not self.frame:
            return
        self.frame.visible = visible
        if self._manipulator:
            self._manipulator.show(visible)

    def show_section_gizmo(self, value):
        """표시 상태를 변경하고 연관 상태를 동기화한다."""
        if self._manipulator:
            self._manipulator.show_gizmo(value)

    def refresh(self):
        """현재 상태를 다시 계산하고 갱신한다."""
        if self._section_model:
            self._section_model.refresh()

    def _on_section_direction_changed(self):
        """이벤트가 발생했을 때 후속 처리를 수행한다."""
        if self._section_model:
            self._section_model.update_section_plane()

