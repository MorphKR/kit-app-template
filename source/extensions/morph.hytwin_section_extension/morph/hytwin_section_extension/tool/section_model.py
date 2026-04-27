# Copyright (c) 2018-2020, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.
#
__all__ = ["SectionModel"]

import carb
import carb.settings
import omni.kit.app
import omni.usd
from carb.eventdispatcher import get_eventdispatcher
from omni.ui import scene as sc
from pxr import Gf, Tf, Usd

from ..common import SECTION_DIRECTION_TOP, SETTING_SECTION_DIRECTION, SectionManager

SETTING_SECTION_TOOL_ROOT = "/exts/morph.hytwin_section_extension/"
SETTING_SECTION_USE_SESSION_LAYER = SETTING_SECTION_TOOL_ROOT + "useSessionLayer"

PLANE_ATTR = "omni:rtx:scene:sectionPlane:plane"
ATTR_SECTION_TRANSFORM = "xformOp:transform"


class SectionModel(sc.AbstractManipulatorModel):
    """섹션 트랜스폼 변화를 추적하고 section plane을 갱신한다."""

    class TransformItem(sc.AbstractManipulatorItem):
        """매니퓰레이터에서 사용하는 트랜스폼 행렬 컨테이너."""

        def __init__(self):
            """트랜스폼을 단위 행렬로 초기화한다."""
            super().__init__()
            self.value = Gf.Matrix4d()

    def __init__(self, viewport_key: str = None, viewport_window=None):
        """모델 상태와 USD 구독을 초기화한다."""
        super().__init__()
        self._usd_context = omni.usd.get_context()
        self._settings = carb.settings.get_settings()
        self._viewport_key = viewport_key
        self._viewport_window = viewport_window
        self._transform = SectionModel.TransformItem()

        section_transform_attr = SectionManager.get_instance().get_transform_attr(viewport_key=self._viewport_key)
        if section_transform_attr:
            self.set_floats(self._transform, section_transform_attr.Get())

        self._stage_sub = get_eventdispatcher().observe_event(
            observer_name=f"morph.hytwin_section_extension.model.{self._viewport_key or 'default'}",
            event_name=self._usd_context.stage_event_name(omni.usd.StageEventType.CLOSING),
            on_event=self._on_stage_closing,
        )

        stage = omni.usd.get_context().get_stage()
        self._usd_listener = Tf.Notice.Register(Usd.Notice.ObjectsChanged, self._on_usd_changed, stage)

    def __del__(self):  # pragma: no cover
        """객체 소멸 시 리소스를 정리한다."""
        self.destroy()

    def destroy(self):  # pragma: no cover
        """구독을 해제하고 참조를 정리한다."""
        if self._stage_sub:
            get_eventdispatcher().unobserve_event(self._stage_sub)
            self._stage_sub = None
        self._settings = None
        self._usd_listener = None
        self._transform = None
        self._viewport_window = None

    def refresh(self):
        """내부 상태를 초기화하고 USD 구독을 다시 생성한다."""
        self._set_section_plane([0, 0, 0, 0])
        self._usd_listener = None
        self._transform.value = Gf.Matrix4d()
        stage = omni.usd.get_context().get_stage()
        self._usd_listener = Tf.Notice.Register(Usd.Notice.ObjectsChanged, self._on_usd_changed, stage)

    def get_item(self, identifier):
        """트랜스폼 아이템을 반환한다."""
        return self._transform

    def get_as_floats(self, item):
        """현재 트랜스폼 값을 반환한다."""
        return self._transform.value

    def _get_section_edit_context(self):
        """현재 섹션 레이어에 대한 편집 컨텍스트를 반환한다."""
        stage = omni.usd.get_context().get_stage()
        sect_layer = self._get_section_layer()
        return Usd.EditContext(stage, sect_layer)

    def _get_section_layer(self):
        """설정값에 따라 session/root 레이어를 선택한다."""
        settings = carb.settings.get_settings()
        use_session_layer = settings.get(SETTING_SECTION_USE_SESSION_LAYER)
        stage = omni.usd.get_context().get_stage()
        if bool(use_session_layer):
            return stage.GetSessionLayer()
        return stage.GetRootLayer()

    def set_floats(self, item, value):
        """트랜스폼 값을 반영하고 section plane을 갱신한다."""
        with self._get_section_edit_context():
            if not value:
                return

            section_transform_attr = SectionManager.get_instance().get_transform_attr(viewport_key=self._viewport_key)
            if section_transform_attr:
                current_value = section_transform_attr.Get()
                if current_value != value:
                    section_transform_attr.Set(value)

            self._transform.value = value
            self.update_section_plane()
            self._item_changed(self._transform)

    def _on_usd_changed(self, notice, stage):
        """USD 속성 변경 시 모델 값을 동기화한다."""
        with self._get_section_edit_context():
            section_transform_attr = SectionManager.get_instance().get_transform_attr(viewport_key=self._viewport_key)
            if not section_transform_attr:
                return
            attr_path = section_transform_attr.GetPath()

            if attr_path in notice.GetChangedInfoOnlyPaths():
                self.set_floats(self._transform, section_transform_attr.Get())

    def _on_stage_closing(self, _):
        """스테이지 종료 시 모델 상태를 초기화한다."""
        self.refresh()
        omni.usd.get_context().set_pending_edit(False)

    def _set_section_plane(self, value: list):
        """현재 viewport의 render product prim에 section plane을 기록한다."""
        try:
            stage = omni.usd.get_context().get_stage()
            # ViewportWidget host가 전달된 경우 해당 viewport_api를 사용한다.
            viewport_api = self._viewport_window.viewport_api if self._viewport_window else None
            if not viewport_api:
                return

            # viewport_api.render_product_path: 현재 카메라 화면의 render prim 경로
            render_path = viewport_api.render_product_path
            prim = stage.GetPrimAtPath(render_path)
            if prim and prim.IsValid():
                if vp_attr := prim.GetAttribute(PLANE_ATTR):
                    vp_attr.Set(value)
        except Exception as e:
            carb.log_warn(f"Failed to set section plane attribute: {e}")

    def update_section_plane(self):
        """현재 트랜스폼 기준으로 section plane을 계산해 적용한다."""
        with self._get_section_edit_context():
            if self._settings.get_as_int(SETTING_SECTION_DIRECTION) == SECTION_DIRECTION_TOP:
                direction = Gf.Vec3d(0, 0, -1)
            else:
                direction = Gf.Vec3d(0, 0, 1)

            point = self._transform.value.ExtractTranslation()
            normal = self._transform.value.TransformDir(direction)
            d = point * normal

            section_plane = [normal[0], normal[1], normal[2], -d]
            self._set_section_plane(section_plane)
