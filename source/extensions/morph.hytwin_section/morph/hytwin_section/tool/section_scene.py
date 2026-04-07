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
    # 단일 뷰포트에 대한 섹션 씬 컨테이너.
    # - SectionModel(데이터/계산)
    # - SectionManipulator(인터랙션/표시)
    # 를 SceneView에 묶어 관리한다.

    def __init__(self, ext_id: str, viewport_window=None, viewport_key: str = None, **kwargs):
        self._ext_id = ext_id
        self._settings = carb.settings.get_settings()
        self._section_model = None
        self._manipulator = None
        self._viewport_window = viewport_window or get_active_viewport_window()
        self._viewport_key = viewport_key
        self.detachable = False
        self._scene_view = None

        # 컷 방향 설정 변경 시, 현재 모델의 section plane을 재계산한다.
        self._cut_direction_setting_tp = omni.kit.app.SettingChangeSubscription(
            SETTING_SECTION_DIRECTION, lambda *_: self._on_section_direction_changed()
        )
        # 뷰포트별 모델을 생성해 viewport_key 기준 상태를 분리한다.
        self._section_model = SectionModel(viewport_key=self._viewport_key, viewport_window=self._viewport_window)

        self.__build_window()

    @property
    def viewport_api(self):
        return self._viewport_window.viewport_api if self._viewport_window else None

    @property
    def viewport_window(self):
        return self._viewport_window

    def destroy(self):
        # 매니퓰레이터/모델/SceneView를 역순으로 해제해 참조와 구독을 정리한다.
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
        """Viewport frame에 SceneView와 SectionManipulator를 구성한다."""
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
        # 프레임 가시성과 매니퓰레이터 가시성을 함께 동기화한다.
        if not hasattr(self, "frame") or not self.frame:
            return
        self.frame.visible = visible
        if self._manipulator:
            self._manipulator.show(visible)

    def show_section_gizmo(self, value):
        # 섹션 위젯 선택/기즈모 표시를 매니퓰레이터에 위임한다.
        if self._manipulator:
            self._manipulator.show_gizmo(value)

    def refresh(self):
        # stage 변경/리셋 상황에서 모델 상태를 초기화한다.
        if self._section_model:
            self._section_model.refresh()

    def _on_section_direction_changed(self):
        # 컷 방향 설정이 바뀌면 즉시 렌더 평면을 갱신한다.
        if self._section_model:
            self._section_model.update_section_plane()
