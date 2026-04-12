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
    """뷰포트에 SceneView/모델/매니퓰레이터를 연결해 관리한다."""

    def __init__(self, ext_id: str, viewport_window=None, viewport_key: str = None, **kwargs):
        """섹션 씬 상태를 초기화하고 UI를 구성한다."""
        self._ext_id = ext_id
        self._settings = carb.settings.get_settings()
        self._section_model = None
        self._manipulator = None
        # 전달된 viewport_window가 있으면(예: ViewportWidget host) 우선 사용하고,
        # 없을 때만 기존 active ViewportWindow를 사용한다.
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
        """현재 연결된 viewport API를 반환한다."""
        return self._viewport_window.viewport_api if self._viewport_window else None

    @property
    def viewport_window(self):
        """현재 연결된 viewport window/host를 반환한다."""
        return self._viewport_window

    def destroy(self):
        """씬 리소스와 구독을 정리한다."""
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
        """섹션 UI를 viewport frame 위에 구성한다."""
        if not self._viewport_window:
            return
        # viewport_window.get_frame(ext_id)에 섹션 UI를 올린다.
        # ViewportWidget host는 이 frame을 타일 내부 overlay frame으로 제공한다.
        self.frame = self._viewport_window.get_frame(self._ext_id)
        with self.frame:
            self._scene_view = sc.SceneView()
            with self._scene_view.scene:
                self._manipulator = SectionManipulator(
                    model=self._section_model, viewport_window=self._viewport_window, viewport_key=self._viewport_key
                )

            # SceneView를 해당 viewport_api에 등록해 섹션 gizmo/면을 렌더링한다.
            # 즉, 여기서 실제 카메라 화면(ViewportWindow/ViewportWidget)에 섹션이 붙는다.
            self._viewport_window.viewport_api.add_scene_view(self._scene_view)

    def show(self, visible: bool):
        """섹션 씬 표시 상태를 전환한다."""
        if not hasattr(self, "frame") or not self.frame:
            return
        self.frame.visible = visible
        if self._manipulator:
            self._manipulator.show(visible)

    def show_section_gizmo(self, value):
        """섹션 기즈모 표시 상태를 전환한다."""
        if self._manipulator:
            self._manipulator.show_gizmo(value)

    def refresh(self):
        """섹션 모델 상태를 새로고침한다."""
        if self._section_model:
            self._section_model.refresh()

    def _on_section_direction_changed(self):
        """섹션 방향 설정 변경 시 section plane을 갱신한다."""
        if self._section_model:
            self._section_model.update_section_plane()
