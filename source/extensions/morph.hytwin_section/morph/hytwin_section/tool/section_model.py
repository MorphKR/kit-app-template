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

        section_transform_attr = SectionManager().get_transform_attr(viewport_key=self._viewport_key)
        if section_transform_attr:
            self.set_floats(self._transform, section_transform_attr.Get())

        self._stage_sub = get_eventdispatcher().observe_event(
            observer_name=f"morph.hytwin_section.model.{self._viewport_key or 'default'}",
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
        self._usd_listener = None
        self._transform = None
        self._viewport_window = None

    def refresh(self):
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
            self._transform.value = value
            self.update_section_plane()
            self._item_changed(self._transform)

    def _on_usd_changed(self, notice, stage):
        with self._get_section_edit_context():
            section_transform_attr = SectionManager().get_transform_attr(viewport_key=self._viewport_key)
            if not section_transform_attr:
                return
            attr_path = section_transform_attr.GetPath()
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
            if self._settings.get_as_int(SETTING_SECTION_DIRECTION) == SECTION_DIRECTION_TOP:
                direction = Gf.Vec3d(0, 0, -1)
            else:
                direction = Gf.Vec3d(0, 0, 1)

            point = self._transform.value.ExtractTranslation()
            normal = self._transform.value.TransformDir(direction)
            d = point * normal
            section_plane = [normal[0], normal[1], normal[2], -d]
            self._set_section_plane(section_plane)
