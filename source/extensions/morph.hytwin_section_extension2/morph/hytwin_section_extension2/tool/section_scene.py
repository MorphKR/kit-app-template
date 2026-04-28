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
from omni.kit.viewport.navigation.core import NAVIGATION_TOOL_OPERATION_ACTIVE
from omni.kit.viewport.utility import get_active_viewport_window
from omni.kit.manipulator.transform.manipulator import Axis, TransformManipulator
from omni.kit.manipulator.transform.simple_transform_model import (
    SimpleRotateChangedGesture,
    SimpleTransformModel,
    SimpleTranslateChangedGesture,
)
from omni.kit.manipulator.transform.settings_constants import c as transform_settings
from omni.kit.manipulator.transform.types import Operation
from omni.ui import scene as sc
from morph.hytwin_viewportwidget_extension.viewport_bridge import get_registered_viewport_hosts
from pxr import Gf

from ..common import (
    CURRENT_TOOL_PATH,
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
    """섹션 매니퓰레이터와 Transform gizmo를 관리하는 씬 컨테이너."""

    def __init__(self, ext_id: str, model: SectionModel, **kwargs):
        self._ext_id = ext_id
        self._settings = carb.settings.get_settings()
        self._section_model = model
        self._manipulator = None
        self._transform_manipulator = None
        self._transform_model = None
        self._transform_model_sub = None
        self._section_model_sub = None
        self._syncing_from_section = False
        self._syncing_from_transform = False
        hosts = get_registered_viewport_hosts() or []
        self._viewport_window = hosts[0] if hosts else get_active_viewport_window()
        self.detachable = False
        self._scene_view = None

        self._cut_direction_setting_tp = omni.kit.app.SettingChangeSubscription(
            SETTING_SECTION_DIRECTION, lambda *_: self._on_section_direction_changed()
        )
        self._transform_op_setting_tp = omni.kit.app.SettingChangeSubscription(
            transform_settings.TRANSFORM_OP_SETTING, lambda *_: self._on_transform_operation_changed()
        )
        self._navigation_op_setting_tp = omni.kit.app.SettingChangeSubscription(
            NAVIGATION_TOOL_OPERATION_ACTIVE, lambda *_: self._on_navigation_operation_changed()
        )
        self._section_enabled_setting_tp = omni.kit.app.SettingChangeSubscription(
            SETTING_SECTION_ENABLED, lambda *_: self._on_section_enabled_changed()
        )

        self.__build_window()

    @property
    def viewport_api(self):
        return self._viewport_window.viewport_api if self._viewport_window else None

    def destroy(self):
        if self._manipulator:
            self._manipulator.destroy()
            self._manipulator = None
        if self._transform_model_sub:
            self._transform_model_sub = None
        if self._section_model_sub:
            self._section_model_sub = None
        if self._transform_manipulator:
            self._transform_manipulator.destroy()
            self._transform_manipulator = None
        self._transform_model = None

        self._section_model = None
        self._settings = None
        self._cut_direction_setting_tp = None
        self._transform_op_setting_tp = None
        self._navigation_op_setting_tp = None
        self._section_enabled_setting_tp = None

        if self._viewport_window and self._scene_view:
            self._viewport_window.viewport_api.remove_scene_view(self._scene_view)

        if self._scene_view:
            self._scene_view.destroy()
            self._scene_view = None

        self._viewport_window = None

    def __build_window(self):
        """viewport frame 위에 SceneView와 조작 UI를 구성한다."""
        self.frame = self._viewport_window.get_frame(self._ext_id)
        with self.frame:
            self._scene_view = sc.SceneView()
            with self._scene_view.scene:
                self._manipulator = SectionManipulator(
                    model=self._section_model,
                    viewport_window=self._viewport_window,
                    on_section_click=self._show_transform_gizmo,
                    on_section_hover_end=self._hide_transform_gizmo,
                )
                self._build_transform_manipulator()
                self._on_section_enabled_changed()
                self._on_navigation_operation_changed()

            self._viewport_window.viewport_api.add_scene_view(self._scene_view)

    def _build_transform_manipulator(self):
        self._transform_model = SimpleTransformModel()
        # gizmo 축을 월드 기준으로 고정한다.
        self._transform_model.global_mode = True
        self._transform_manipulator = TransformManipulator(
            size=1.0,
            axes=Axis.ALL,
            enabled=False,
            model=self._transform_model,
            gestures=[SimpleTranslateChangedGesture(), SimpleRotateChangedGesture()],
        )
        self._transform_model_sub = self._transform_model.subscribe_item_changed_fn(self._on_transform_item_changed)
        self._section_model_sub = self._section_model.subscribe_item_changed_fn(self._on_section_model_item_changed)
        # 초기 표시값과 내부 모델값이 다르지 않도록 시작 시 한 번 동기화한다.
        self._sync_transform_model_from_section()
        self._on_transform_operation_changed()

    def _sync_transform_model_from_section(self):
        if not self._transform_model or not self._section_model:
            return
        # SectionModel(USD 기준) -> TransformManipulator 모델로 역방향 동기화
        section_transform = self._section_model.get_as_floats(self._section_model.get_item("transform"))
        if not section_transform:
            return
        translation = section_transform.ExtractTranslation()
        rotation = section_transform.ExtractRotation()
        try:
            rx, ry, rz = rotation.Decompose(
                Gf.Vec3d(1.0, 0.0, 0.0),
                Gf.Vec3d(0.0, 1.0, 0.0),
                Gf.Vec3d(0.0, 0.0, 1.0),
            )
        except Exception:
            rx, ry, rz = (0.0, 0.0, 0.0)  # 회전 분해 실패 시 기본값

        self._syncing_from_section = True
        try:
            self._transform_model.set_floats(
                self._transform_model.get_item("translate"), [translation[0], translation[1], translation[2]]
            )
            self._transform_model.set_floats(
                self._transform_model.get_item("rotate"), [float(rx), float(ry), float(rz)]
            )
        finally:
            self._syncing_from_section = False

    def _on_transform_item_changed(self, model, item):
        if self._syncing_from_section:
            return
        if not self._section_model:
            return
        if not hasattr(item, "operation"):
            return
        if item.operation not in (Operation.TRANSLATE, Operation.ROTATE):
            return
        # TransformManipulator 모델 -> SectionModel(USD 속성)으로 정방향 동기화
        current = self._section_model.get_as_floats(self._section_model.get_item("transform"))
        if current is None:
            current = Gf.Matrix4d()

        if item.operation == Operation.TRANSLATE:
            t = model.get_as_floats(model.get_item("translate"))
            current.SetTranslateOnly(Gf.Vec3d(t[0], t[1], t[2]))
        elif item.operation == Operation.ROTATE:
            r = model.get_as_floats(model.get_item("rotate"))
            rot = Gf.Rotation(Gf.Vec3d(1, 0, 0), r[0]) * Gf.Rotation(Gf.Vec3d(0, 1, 0), r[1]) * Gf.Rotation(
                Gf.Vec3d(0, 0, 1), r[2]
            )
            current.SetRotateOnly(rot)

        self._syncing_from_transform = True
        try:
            self._section_model.set_floats(self._section_model.get_item("transform"), current)
        finally:
            self._syncing_from_transform = False

    def _on_section_model_item_changed(self, _model, _item):
        # align/move 등 외부 변경 후 다음 드래그가 이전 값에서 시작되지 않도록 재동기화
        if self._syncing_from_transform:
            return
        self._sync_transform_model_from_section()

    def _on_transform_operation_changed(self):
        if not self._transform_model:
            return
        # W/E 단축키로 바뀐 전역 transform 모드를 viewportwidget gizmo에도 맞춘다.
        op = self._settings.get(transform_settings.TRANSFORM_OP_SETTING)
        if op == transform_settings.TRANSFORM_OP_ROTATE:
            self._transform_model.set_operation(Operation.ROTATE)
        elif op == transform_settings.TRANSFORM_OP_MOVE:
            self._transform_model.set_operation(Operation.TRANSLATE)

    def _show_transform_gizmo(self):
        if not self._settings.get_as_bool(SETTING_SECTION_ENABLED):
            return
        self._settings.set_string(CURRENT_TOOL_PATH, "section")
        self._settings.set(NAVIGATION_TOOL_OPERATION_ACTIVE, "section")
        if self._transform_manipulator:
            self._transform_manipulator.enabled = True

    def _hide_transform_gizmo(self):
        self._settings.set_string(CURRENT_TOOL_PATH, "navigation")
        self._settings.set(NAVIGATION_TOOL_OPERATION_ACTIVE, "orbit")
        if self._transform_manipulator:
            self._transform_manipulator.enabled = False

    def _on_section_enabled_changed(self):
        enabled = self._settings.get_as_bool(SETTING_SECTION_ENABLED)
        if self._manipulator:
            self._manipulator.set_interaction_enabled(enabled)
            self._manipulator.show(enabled)
            if not enabled:
                self._manipulator.show_gizmo(False)
        if self._transform_manipulator:
            self._transform_manipulator.enabled = enabled and (self._settings.get(NAVIGATION_TOOL_OPERATION_ACTIVE) == "section")

        if enabled:
            self._settings.set_string(CURRENT_TOOL_PATH, "section")
            self._settings.set(NAVIGATION_TOOL_OPERATION_ACTIVE, "section")
        else:
            self._settings.set_string(CURRENT_TOOL_PATH, "navigation")
            self._settings.set(NAVIGATION_TOOL_OPERATION_ACTIVE, "orbit")

    def _on_navigation_operation_changed(self):
        enabled = self._settings.get_as_bool(SETTING_SECTION_ENABLED)
        op = self._settings.get(NAVIGATION_TOOL_OPERATION_ACTIVE)
        if self._transform_manipulator:
            self._transform_manipulator.enabled = enabled and (op == "section")
        if self._manipulator and (not enabled or op != "section"):
            self._manipulator.show_gizmo(False)

    def show(self, visible: bool):
        enabled = self._settings.get_as_bool(SETTING_SECTION_ENABLED)
        self.frame.visible = bool(visible and enabled)
        if self._manipulator:
            self._manipulator.show(bool(visible and enabled))
        if not visible or not enabled:
            self._settings.set_string(CURRENT_TOOL_PATH, "navigation")
            self._settings.set(NAVIGATION_TOOL_OPERATION_ACTIVE, "orbit")

    def show_section_gizmo(self, value):
        if self._manipulator:
            self._manipulator.show_gizmo(value)

    def _on_section_direction_changed(self):
        if self._section_model:
            self._section_model.update_section_plane()
