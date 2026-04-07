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

SETTING_SECTION_TOOL_ROOT = "/exts/morph.hytwin_section/"
SETTING_SECTION_USE_SESSION_LAYER = SETTING_SECTION_TOOL_ROOT + "useSessionLayer"

PLANE_ATTR = "omni:rtx:scene:sectionPlane:plane"
ATTR_SECTION_TRANSFORM = "xformOp:transform"


class SectionModel(sc.AbstractManipulatorModel):
    # 뷰포트별 섹션 매니퓰레이터 모델.
    # - 위젯 transform 값을 추적
    # - transform + 컷 방향으로 section plane 계산
    # - 계산 결과를 render product prim 속성에 반영
    class TransformItem(sc.AbstractManipulatorItem):
        def __init__(self):
            super().__init__()
            self.value = Gf.Matrix4d()

    def __init__(self, viewport_key: str = None, viewport_window=None):
        super().__init__()
        self._usd_context = omni.usd.get_context()
        self._settings = carb.settings.get_settings()
        self._viewport_key = viewport_key
        self._viewport_window = viewport_window
        self._transform = SectionModel.TransformItem()

        # 현재 viewport 키에 해당하는 섹션 transform을 초기값으로 동기화한다.
        section_transform_attr = SectionManager().get_transform_attr(viewport_key=self._viewport_key)
        if section_transform_attr:
            self.set_floats(self._transform, section_transform_attr.Get())

        # Stage 종료 시 모델을 안전하게 리셋하기 위해 이벤트를 구독한다.
        self._stage_sub = get_eventdispatcher().observe_event(
            observer_name=f"morph.hytwin_section.model.{self._viewport_key or 'default'}",
            event_name=self._usd_context.stage_event_name(omni.usd.StageEventType.CLOSING),
            on_event=self._on_stage_closing,
        )

        stage = omni.usd.get_context().get_stage()
        # USD 객체 변경을 감시해 외부 변경(속성 수정)을 모델 값에 반영한다.
        self._usd_listener = Tf.Notice.Register(Usd.Notice.ObjectsChanged, self._on_usd_changed, stage)

    def __del__(self):  # pragma: no cover
        self.destroy()

    def destroy(self):  # pragma: no cover
        if self._stage_sub:
            get_eventdispatcher().unobserve_event(self._stage_sub)
            self._stage_sub = None
        self._settings = None
        self._usd_listener = None
        self._transform = None
        self._viewport_window = None

    def refresh(self):
        # 섹션 평면/모델 행렬을 기본 상태로 초기화하고 리스너를 재구독한다.
        self._set_section_plane([0, 0, 0, 0])
        self._usd_listener = None
        self._transform.value = Gf.Matrix4d()
        stage = omni.usd.get_context().get_stage()
        self._usd_listener = Tf.Notice.Register(Usd.Notice.ObjectsChanged, self._on_usd_changed, stage)

    def get_item(self, identifier):
        return self._transform

    def get_as_floats(self, item):
        return self._transform.value

    def _get_section_edit_context(self):
        stage = omni.usd.get_context().get_stage()
        sect_layer = self._get_section_layer()
        return Usd.EditContext(stage, sect_layer)

    def _get_section_layer(self):
        settings = carb.settings.get_settings()
        use_session_layer = settings.get(SETTING_SECTION_USE_SESSION_LAYER)
        stage = omni.usd.get_context().get_stage()
        if bool(use_session_layer):
            return stage.GetSessionLayer()
        return stage.GetRootLayer()

    def set_floats(self, item, value):
        with self._get_section_edit_context():
            if not value:
                return
            # 모델 값 갱신 -> 섹션 평면 재계산 -> UI 갱신 신호 순으로 처리한다.
            self._transform.value = value
            self.update_section_plane()
            self._item_changed(self._transform)

    def _on_usd_changed(self, notice, stage):
        with self._get_section_edit_context():
            section_transform_attr = SectionManager().get_transform_attr(viewport_key=self._viewport_key)
            if not section_transform_attr:
                return
            attr_path = section_transform_attr.GetPath()
            # 정보 변경 경로에 transform attr이 포함된 경우에만 모델을 갱신한다.
            if attr_path in notice.GetChangedInfoOnlyPaths():
                self.set_floats(self._transform, section_transform_attr.Get())

    def _on_stage_closing(self, _):
        self.refresh()
        omni.usd.get_context().set_pending_edit(False)

    def _set_section_plane(self, value: list):
        try:
            stage = omni.usd.get_context().get_stage()
            viewport_api = self._viewport_window.viewport_api if self._viewport_window else None
            if not viewport_api:
                # viewport가 아직 준비되지 않은 경우는 조용히 스킵한다.
                return
            render_path = viewport_api.render_product_path
            prim = stage.GetPrimAtPath(render_path)
            if prim and prim.IsValid():
                if vp_attr := prim.GetAttribute(PLANE_ATTR):
                    vp_attr.Set(value)
        except Exception as e:
            carb.log_warn(f"Failed to set section plane attribute: {e}")

    def update_section_plane(self):
        with self._get_section_edit_context():
            # 컷 방향 설정(Top/Bottom)에 따라 법선 기준축을 결정한다.
            if self._settings.get_as_int(SETTING_SECTION_DIRECTION) == SECTION_DIRECTION_TOP:
                direction = Gf.Vec3d(0, 0, -1)
            else:
                direction = Gf.Vec3d(0, 0, 1)

            point = self._transform.value.ExtractTranslation()
            normal = self._transform.value.TransformDir(direction)
            d = point * normal
            # 평면 방정식 [nx, ny, nz, d] 형식으로 변환한다. (n·x + d = 0)
            section_plane = [normal[0], normal[1], normal[2], -d]
            self._set_section_plane(section_plane)
