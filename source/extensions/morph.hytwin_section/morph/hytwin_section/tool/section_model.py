# Copyright (c) 2018-2020, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.
#
__all__ = ["SectionModel"]

import carb.settings
import omni.kit.app
import omni.usd
from carb.eventdispatcher import get_eventdispatcher
from omni.kit.viewport.utility import get_active_viewport
from omni.ui import scene as sc
from pxr import Gf, Tf, Usd

from ..common import SECTION_DIRECTION_TOP, SETTING_SECTION_DIRECTION, SETTING_SECTION_PLANE, SectionManager

SETTING_SECTION_TOOL_ROOT = "/exts/morph.hytwin_section/"
SETTING_SECTION_USE_SESSION_LAYER = SETTING_SECTION_TOOL_ROOT + "useSessionLayer"

PLANE_ATTR = "omni:rtx:scene:sectionPlane:plane"


class SectionModel(sc.AbstractManipulatorModel):
    """
    USD의 섹션 위젯 transform을 추적하고,
    계산된 plane 값을 활성 뷰포트 렌더 프라임에 반영하는 씬 매니퓰레이터 모델.
    """

    class TransformItem(sc.AbstractManipulatorItem):
        """
        매니퓰레이터가 편집하는 섹션 위젯의 transform 값을 담는 모델 아이템.
        """

        def __init__(self):
            super().__init__()
            self.value = Gf.Matrix4d()

    def __init__(self):
        # 스테이지가 다시 열릴 때 모델 상태를 재구성할 수 있도록 초기화한다.
        super().__init__()

        self._usd_context = omni.usd.get_context()
        self._settings = carb.settings.get_settings()
        self._transform = SectionModel.TransformItem()
        section_transform_attr = SectionManager().get_transform_attr()
        if section_transform_attr:  # pragma: no cover
            self.set_floats(self._transform, section_transform_attr.Get())

        self._stage_sub = get_eventdispatcher().observe_event(
            observer_name="morph.hytwin_section.model",
            event_name=self._usd_context.stage_event_name(omni.usd.StageEventType.CLOSING),
            on_event=self._on_stage_closing,
        )

        stage = omni.usd.get_context().get_stage()
        self._usd_listener = Tf.Notice.Register(Usd.Notice.ObjectsChanged, self._on_usd_changed, stage)

    def __del__(self):  # pragma: no cover
        self.destroy()

    def destroy(self):  # pragma: no cover
        if self._stage_sub:
            get_eventdispatcher().unobserve_event(self._stage_sub)
            self._stage_sub = None
        self._settings = None
        self._section_manager = None
        self._usd_listener = None
        self._transform = None

    def refresh(self):
        with self._get_section_edit_context():
            # 섹션 평면을 기본값으로 되돌린다.
            self._set_section_plane([0, 0, 0, 0])

        # 현재 stage 인스턴스 기준으로 USD 변경 리스너를 다시 등록한다.
        self._usd_listener = None
        # 위젯 transform도 항등행렬로 초기화한다.
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
        else:  # pragma: no cover
            return stage.GetRootLayer()

    def set_floats(self, item, value):
        with self._get_section_edit_context():
            if not value:  # pragma: no cover
                return
            # 모델 값 반영 후 렌더 섹션 평면을 즉시 갱신한다.
            self._transform.value = value
            self.update_section_plane()
            # 매니퓰레이터가 다시 그려지도록 변경 이벤트를 발생시킨다.
            self._item_changed(self._transform)

    def _on_usd_changed(self, notice, stage):
        with self._get_section_edit_context():
            section_transform_attr = SectionManager().get_transform_attr()
            if section_transform_attr:
                attr_path = section_transform_attr.GetPath()
                if attr_path in notice.GetChangedInfoOnlyPaths():
                    self.set_floats(self._transform, section_transform_attr.Get())

    def _on_stage_closing(self, _):
        self.refresh()
        omni.usd.get_context().set_pending_edit(False)

    def _set_section_plane(self, value: list):
        try:
            # 확장 시작 시 상호 갱신 루프를 피하기 위해 scene 준비 여부를 먼저 확인한다.
            from .section_tool import SectionTool

            if not (viewport_scene := SectionTool().scene):
                carb.log_warn("SectionTool viewport scene is not available to set section plane attribute.")
                return

            viewport_api = viewport_scene.viewport_api
            render_path = viewport_api.render_product_path
            stage = omni.usd.get_context().get_stage()
            prim = stage.GetPrimAtPath(render_path)
            if prim and prim.IsValid():
                if vp_attr := prim.GetAttribute(PLANE_ATTR):
                    vp_attr.Set(value)
                    return
        except Exception as e:
            carb.log_warn(f"Failed to set section plane attribute: {e}")

    def update_section_plane(self):
        with self._get_section_edit_context():
            # 현재 transform과 컷 방향 설정으로 렌더 섹션 평면을 계산한다.
            if self._settings.get_as_int(SETTING_SECTION_DIRECTION) == SECTION_DIRECTION_TOP:
                direction = Gf.Vec3d(0, 0, -1)
            else:
                direction = Gf.Vec3d(0, 0, 1)

            point = self._transform.value.ExtractTranslation()
            normal = self._transform.value.TransformDir(direction)
            # 렌더러 평면 방정식 형식: [nx, ny, nz, d]
            # n·x + d = 0, d = -(n·p0)
            d = point * normal
            sectionPlane = [normal[0], normal[1], normal[2], -d]

            self._set_section_plane(sectionPlane)

            # 과거에는 RTX settings 경로에 직접 기록했지만, 라이브 세션에서는
            # 동기화 이슈가 있어 render product prim 속성에 직접 반영한다.
            # self._settings.set_float_array(SETTING_SECTION_PLANE, sectionPlane)
