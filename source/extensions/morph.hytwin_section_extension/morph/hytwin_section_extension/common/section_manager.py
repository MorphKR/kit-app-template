# Copyright (c) 2018-2021, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.
#
import copy
import re

import carb
import carb.settings
import carb.tokens
import omni.kit.app
import omni.usd
from omni.kit.viewport.utility import get_active_viewport_camera_path
from omni.kit.viewport.utility.camera_state import ViewportCameraState
from pxr import Gf, Sdf, Usd, UsdGeom
from ..extension import get_instance

from .constant import (
    DEFAULT_SECTION_TOP,
    HIDE_IN_STAGE_WINDOW,
    SETTING_SECTION_DIRECTION,
    SETTING_SECTION_ENABLED,
    SETTING_SECTION_LIGHT,
    SETTING_SECTION_USE_SESSION_LAYER,
)
from .utils import Singleton

ATTR_SECTION_DIRECTION = "primvars:section:direction:top"
ATTR_SECTION_LIGHT = "primvars:section:light"
ATTR_SECTION_TRANSFORM = "xformOp:transform"
SECTION_LAYER_EXT = ".section.usda"
SECTION_VARIANT_NAME = "sectionVariant"
SECTION_TOOL_PATH = "/SectionTools"
SECTION_PRIM_PATH = "/Section_Tool_Object"
VIEW_LAYER_EXT = ".view.usd"


class CutDirection:
    Top = "Top"
    Bottom = "Bottom"


class WidgetAlignment:
    X = "x"
    Y = "y"
    Z = "z"


@Singleton
class SectionManager:
    # ?뱀뀡 variant? ?꾩젽 prim ?띿꽦??愿由ы븯??以묒븰 ?곹깭 愿由ъ옄.
    # UI ?⑤꼸怨?留ㅻ땲?곕젅?댄꽣???몄쭛 ?붿껌? 紐⑤몢 ???대옒?ㅻ? ?듯빐 泥섎━?쒕떎.
    def __init__(self):
        self._section_variants = None
        self._last_variant_id = 0
        self._on_added_section_fn = None
        self._settings = carb.settings.get_settings()
        purposes = [UsdGeom.Tokens.default_]
        self._bboxcache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), purposes)

        self.refresh()

    def __del__(self):  # pragma: no cover
        self.destroy()

    def destroy(self):
        self._settings = None
        self._on_added_section_fn = None
        self._bboxcache = None

    @property
    def section_names(self):
        return list(self._section_variants.keys())

    @property
    def section_count(self):
        return len(self._section_variants) if self._section_variants else 0

    def clear(self):
        if self._section_variants:
            with self._get_section_edit_context():
                if self._stage and self._stage.GetPrimAtPath(f"{SECTION_TOOL_PATH}{SECTION_PRIM_PATH}"):
                    self._section_variants = {}
                else:
                    self._section_variants = {}
                    self._last_variant_id = 0

        self._stage = None
        self._section_variant_set = None
        self._widget_prim = None
        self._section_transform_attr = None

    def refresh(self):
        self.clear()
        self._stage = omni.usd.get_context().get_stage()
        self._load_section_variants()

    def set_added_section_callback(self, cb: callable):
        self._on_added_section_fn = cb

    def set_section_enabled(self, enabled: bool) -> None:
        if not self._settings:
            return
        self._settings.set_bool(SETTING_SECTION_ENABLED, bool(enabled))

        inst = get_instance()
        if inst:
            inst.show_window(None, enabled)

    def is_section_enabled(self) -> bool:
        if not self._settings:
            return False
        return self._settings.get_as_bool(SETTING_SECTION_ENABLED)

    def add_section(self):
        with self._get_section_edit_context():

            section = self._get_section_from_widget(is_new=True)
            if section is None:  # pragma: no cover
                carb.log_error("[SectionTool] Failed to get section info!")
                return None


            self._add_section_internal(section)

            if self._on_added_section_fn:
                self._on_added_section_fn(section["name"])

            self.save_section(section["name"])

    def align_widget(self, align):
        with self._get_section_edit_context():
            transform_attr = self._resolve_target_transform_attr()
            if not transform_attr:  # pragma: no cover
                return
            transform = transform_attr.Get()
            if align == WidgetAlignment.X:
                rotation = Gf.Rotation(Gf.Vec3d(0, 1, 0), 90) * Gf.Rotation(Gf.Vec3d(1, 0, 0), 90)
            elif align == WidgetAlignment.Y:
                rotation = Gf.Rotation(Gf.Vec3d(1, 0, 0), -90) * Gf.Rotation(Gf.Vec3d(0, 1, 0), -90)
            else:
                rotation = Gf.Rotation().SetIdentity()
            transform.SetRotateOnly(rotation)
            transform_attr.Set(transform)

    def rotate_widget(self, align, angle):
        with self._get_section_edit_context():
            transform_attr = self._resolve_target_transform_attr()
            if transform_attr:
                transform = transform_attr.Get()
                rotation = transform.ExtractRotation()
                if align == WidgetAlignment.X:
                    rotate_axis = rotation.TransformDir(Gf.Vec3d(1, 0, 0))
                    rotate_to = Gf.Rotation(rotate_axis, angle)
                elif align == WidgetAlignment.Y:
                    rotate_axis = rotation.TransformDir(Gf.Vec3d(0, 1, 0))
                    rotate_to = Gf.Rotation(rotate_axis, angle)
                else:
                    rotate_axis = rotation.TransformDir(Gf.Vec3d(0, 0, 1))
                    rotate_to = Gf.Rotation(rotate_axis, angle)
                rotation *= rotate_to
                transform.SetRotateOnly(rotation)
                transform_attr.Set(transform)

    def set_widget_position(self, position):
        with self._get_section_edit_context():
            transform_attr = self._resolve_target_transform_attr()
            if transform_attr:
                transform = transform_attr.Get()
                transform.SetTranslateOnly(position)
                transform_attr.Set(transform)

    def _is_section_widget_path(self, prim_path: str) -> bool:
        return bool(prim_path and str(prim_path).endswith(SECTION_PRIM_PATH))

    def _get_selected_section_transform_attr(self):
        usd_context = omni.usd.get_context()
        selection = usd_context.get_selection() if usd_context else None
        if not selection:
            return None

        selected_paths = selection.get_selected_prim_paths() or []
        for prim_path in reversed(selected_paths):
            if not self._is_section_widget_path(prim_path):
                continue
            prim = self._stage.GetPrimAtPath(prim_path) if self._stage else None
            if prim and prim.IsValid():
                attr = prim.GetAttribute(ATTR_SECTION_TRANSFORM)
                if attr:
                    return attr
        return None

    def _resolve_target_transform_attr(self):
        # Priority:
        # 1) currently selected Section_Tool_Object
        # 2) cached default transform attr (legacy fallback)
        selected_attr = self._get_selected_section_transform_attr()
        if selected_attr:
            return selected_attr

        if self._section_transform_attr:
            return self._section_transform_attr

        if self.get_section_widget_prim(create_if_not_exist=True):
            return self._section_transform_attr
        return None

    def set_widget_position_from_prim_path(self, prim_path: str) -> bool:
        if not prim_path:
            carb.log_warn("[SectionTool] set_widget_position_from_prim_path: empty prim path")
            return False

        if not self._stage:
            self._stage = omni.usd.get_context().get_stage()
        if not self._stage:
            carb.log_warn("[SectionTool] set_widget_position_from_prim_path: stage is not ready")
            return False

        # Ensure target section transform exists (selected section first, fallback default).
        if not self._resolve_target_transform_attr():
            carb.log_warn("[SectionTool] set_widget_position_from_prim_path: section transform attribute is missing")
            return False

        prim = self._stage.GetPrimAtPath(prim_path)
        if not prim or not prim.IsValid():
            carb.log_warn(f"[SectionTool] set_widget_position_from_prim_path: invalid prim path: {prim_path}")
            return False

        center = self._get_prim_world_center(prim)
        if center is None:
            carb.log_warn(f"[SectionTool] set_widget_position_from_prim_path: failed to compute center: {prim_path}")
            return False
        self.set_widget_position(center)
        carb.log_info(f"[SectionTool] section moved to prim center: {prim_path} -> {center}")
        return True

    def _get_prim_world_center(self, prim):
        # Prefer world-space bounding-box center for visible geometry.
        try:
            bound = self._bboxcache.ComputeWorldBound(prim).ComputeAlignedRange()
            if bound and not bound.IsEmpty():
                return bound.GetMidpoint()
        except Exception:  # pragma: no cover
            pass

        # Fallback for non-boundable prims: world transform translation.
        try:
            xform = UsdGeom.Xformable(prim)
            matrix = xform.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            return matrix.ExtractTranslation()
        except Exception:  # pragma: no cover
            return None

    def _get_next_available_name(self):
        self._last_variant_id += 1
        if self._last_variant_id > 999:
            self._last_variant_id = 1
        name = "Section_" + "{:03d}".format(self._last_variant_id)
        # OM-88315 - Fix for a rename becoming a part of an upcoming variant ID value
        if name in self._section_variants:
            self._last_variant_id += 1
            name = "Section_" + "{:03d}".format(self._last_variant_id)
        return name

    def _add_section_internal(self, section):
        with self._get_section_edit_context():
            variant_set = self._get_section_variant_set(create_if_not_exist=True)
            if variant_set is None:  # pragma: no cover
                carb.log_error("[SectionTool] No section varaint defined!")
                return None

            name = section["name"]
            self._section_variants[name] = section


            carb.log_info(f"[SectionTool] Section variant {name} added, need to save manually")

            variant_set.AddVariant(name)
            variant_set.SetVariantSelection(name)
            with variant_set.GetVariantEditContext():
                self.set_direction(section["direction"])
                self._set_light(section["light"])
                self._section_transform_attr.Set(section["transform"])

            return section

    def _set_section_attribute(self, name, value, type_name):
        with self._get_section_edit_context():
            if not self._widget_prim:
                return
            if self._widget_prim.HasAttribute(name):
                attribute = self._widget_prim.GetAttribute(name)
            else:
                attribute = self._widget_prim.CreateAttribute(name, type_name)
            attribute.Set(value)

    def _get_section_attribute(self, name, default):
        with self._get_section_edit_context():
            if self._widget_prim and self._widget_prim.HasAttribute(name):
                attribute = self._widget_prim.GetAttribute(name)
                value = attribute.Get()
                return value

            return default

    # TODO: Suspect unused code; remove if so
    def _clear_section_attribute(self, name):  # pragma: no cover
        if self._widget_prim.HasAttribute(name):
            attribute = self._widget_prim.GetAttribute(name)
            attribute.Clear()

    def _set_light(self, value):
        self._set_section_attribute(ATTR_SECTION_LIGHT, value, Sdf.ValueTypeNames.Bool)

    # TODO: Suspect unused code; remove if so
    def _get_light(self):  # pragma: no cover
        return self._get_section_attribute(ATTR_SECTION_LIGHT, False)

    # TODO: Suspect unused code; remove if so
    def _clear_light(self):  # pragma: no cover
        self._clear_section_attribute(ATTR_SECTION_LIGHT)

    def set_direction(self, value):
        self._set_section_attribute(ATTR_SECTION_DIRECTION, value, Sdf.ValueTypeNames.Bool)

    def get_direction(self):
        return self._get_section_attribute(ATTR_SECTION_DIRECTION, DEFAULT_SECTION_TOP)

    def _create_section_spawn_point(self) -> Gf.Vec3d:

        camera_path = get_active_viewport_camera_path()
        camera_state = ViewportCameraState(camera_path)

        camera_pos = camera_state.position_world

        camera_prim = camera_state.usd_camera.GetPrim()
        if camera_prim.GetAttribute("omni:kit:centerOfInterest").Get() is None:
            zlen = camera_pos.GetLength()
            camera_prim.CreateAttribute(
                "omni:kit:centerOfInterest", Sdf.ValueTypeNames.Vector3d, True, Sdf.VariabilityUniform
            ).Set(Gf.Vec3d(0, 0, -zlen))

        camera_target = camera_state.target_world

        forward_vector = (camera_target - camera_pos).GetNormalized()
        return (forward_vector * 1000) + camera_pos

    # TODO: Suspect unused code; remove if so
    def _clear_direction(self):  # pragma: no cover
        with self._get_section_edit_context():
            self._clear_section_attribute(ATTR_SECTION_DIRECTION)

    def get_transform_attr(self, viewport_key: str = None):
        with self._get_section_edit_context():
            if viewport_key:
                widget_prim = self.get_section_widget_prim(create_if_not_exist=True, viewport_key=viewport_key)
                if not widget_prim:
                    return None
                return widget_prim.GetAttribute(ATTR_SECTION_TRANSFORM)
            if self._section_transform_attr:
                return self._section_transform_attr
            return None

    def _load_section_variants(self):
        with self._get_section_edit_context():
            self._section_variants = {}
            self._section_files = {}
            self._last_variant_id = 0

            carb.log_info("[SectionTool] Load section variants")
            vset = self._get_section_variant_set()
            if vset is None:
                return


            for name in vset.GetVariantNames():
                carb.log_info(f"[SectionTool] Found variant {name}")
                self._section_variants[name] = None
                # Get last variant id
                match = re.search(r"_(\d+)$", name)
                if match:
                    number = int(match.group(1))
                    if number > self._last_variant_id:
                        self._last_variant_id = number

    def save_section(self, name):
        with self._get_section_edit_context():
            if name not in self._section_variants:  # pragma: no cover
                carb.log_error(f"[SectionTool] {name} not found in variants")
                return None

            vset = self._get_section_variant_set(create_if_not_exist=True)
            if vset is None:  # pragma: no cover
                return None


            section = self._get_section_from_widget(name)

            carb.log_info(f"[SectionTool] Save section to variant {name}")
            self._section_variants[name] = copy.deepcopy(section)

            # ?꾩옱 ?뱀뀡 ?곹깭瑜??좏깮??variant??湲곕줉?쒕떎.
            vset.SetVariantSelection(name)
            with vset.GetVariantEditContext():
                self.set_direction(section["direction"])
                self._set_light(section["light"])
                self._section_transform_attr = self._widget_prim.GetAttribute(ATTR_SECTION_TRANSFORM)
                self._section_transform_attr.Set(section["transform"])

            return section

    def _get_section_from_widget(self, name=None, is_new: bool = False):
        with self._get_section_edit_context():
            widget_prim = self.get_section_widget_prim(create_if_not_exist=True)

            if not widget_prim:  # pragma: no cover
                return None

            direction_top = self.get_direction()

            if is_new:
                spawn_pos = self._create_section_spawn_point()
                transform = Gf.Matrix4d()
                transform.SetTranslateOnly(spawn_pos)
            else:
                transform = self._section_transform_attr.Get()

            section = {
                "name": self._get_next_available_name() if name is None else name,
                "direction": direction_top,
                "light": self._settings.get_as_bool(SETTING_SECTION_LIGHT),
                "transform": transform,
            }
            return section

    def _get_section_variant_set(self, create_if_not_exist=False):
        with self._get_section_edit_context():
            if not self._stage:  # pragma: no cover
                return None
            if self._section_variant_set is None:
                widget_prim = self.get_section_widget_prim(create_if_not_exist=create_if_not_exist)
                if widget_prim:
                    variant_sets = self._widget_prim.GetVariantSets()
                    if SECTION_VARIANT_NAME in variant_sets.GetNames():
                        self._section_variant_set = variant_sets.GetVariantSet(SECTION_VARIANT_NAME)
                    else:
                        if create_if_not_exist:
                            carb.log_info("[SectionTool] Add variant set")
                            self._section_variant_set = variant_sets.AddVariantSet(SECTION_VARIANT_NAME)
                        else:  # pragma: no cover
                            return None

            return self._section_variant_set
    def _sanitize_viewport_key(self, viewport_key: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_]", "_", str(viewport_key or "default"))
        return safe.strip("_") or "default"

    def _get_section_widget_path(self, section_tool_path: str, viewport_key: str = None) -> str:
        if not viewport_key:
            return section_tool_path + SECTION_PRIM_PATH
        safe_key = self._sanitize_viewport_key(viewport_key)
        return f"{section_tool_path}/{safe_key}{SECTION_PRIM_PATH}"

    def get_section_widget_prim(self, create_if_not_exist=False, viewport_key: str = None):
        with self._get_section_edit_context():
            if self._widget_prim and not viewport_key:
                return self._widget_prim

            if not self._stage:
                self._stage = omni.usd.get_context().get_stage()

            section_tool_path = self._get_section_tool_path()
            section_prim_path = self._get_section_widget_path(section_tool_path, viewport_key)

            widget_prim = self._stage.GetPrimAtPath(section_prim_path)

            if widget_prim:
                if not widget_prim.IsA(UsdGeom.Xformable):
                    widget_prim = self._stage.DefinePrim(section_prim_path, "Xform")
            elif create_if_not_exist:
                widget_prim = self._stage.DefinePrim(section_prim_path, "Xform")

            if not widget_prim:
                return None

            xformable = UsdGeom.Xformable(widget_prim)
            section_transform_attr = widget_prim.GetAttribute(ATTR_SECTION_TRANSFORM)
            if not section_transform_attr:
                xformable.AddXformOp(UsdGeom.XformOp.TypeTransform)
                section_transform_attr = widget_prim.GetAttribute(ATTR_SECTION_TRANSFORM)

                spawn_pos = self._create_section_spawn_point()
                transform = Gf.Matrix4d()
                transform.SetTranslateOnly(spawn_pos)
                section_transform_attr.Set(transform)

            self._tool_prim = self._stage.GetPrimAtPath(section_tool_path)
            self._tool_prim.SetMetadata(HIDE_IN_STAGE_WINDOW, True)

            if not viewport_key:
                self._widget_prim = widget_prim
                self._section_transform_attr = section_transform_attr

            return widget_prim

    def _get_section_tool_path(self):
        with self._get_section_edit_context():
            if self._stage.HasDefaultPrim():
                defaultPath = self._stage.GetDefaultPrim().GetPath().pathString
                old_path = defaultPath + SECTION_TOOL_PATH
                if self._stage.GetPrimAtPath(old_path):
                    return old_path
            return SECTION_TOOL_PATH

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

    def get_center_of_prims(self, prim_paths: list):
        with self._get_section_edit_context():
            all_bound = Gf.Range3d()
            if isinstance(prim_paths, list) and len(prim_paths) > 0:
                for path in prim_paths:
                    prim = self._stage.GetPrimAtPath(path)

                    bound = self._bboxcache.ComputeWorldBound(prim).ComputeAlignedRange()
                    if bound.IsEmpty():
                        for child in Usd.PrimRange(prim):
                            if child.IsA(UsdGeom.Boundable):
                                sub_bound = self._bboxcache.ComputeWorldBound(child).ComputeAlignedRange()
                                bound.UnionWith(sub_bound)
                    all_bound.UnionWith(bound)
            return all_bound.GetMidpoint()
