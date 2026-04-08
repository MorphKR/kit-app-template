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

from .constant import (
    DEFAULT_SECTION_TOP,
    HIDE_IN_STAGE_WINDOW,
    SETTING_SECTION_DIRECTION,
    SETTING_SECTION_ENABLED,
    SETTING_SECTION_LIGHT,
    SETTING_SECTION_MANIPULATOR,
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
    """이 모듈의 주요 기능을 구성하는 클래스다."""
    Top = "Top"
    Bottom = "Bottom"


class WidgetAlignment:
    """이 모듈의 주요 기능을 구성하는 클래스다."""
    X = "x"
    Y = "y"
    Z = "z"


@Singleton
class SectionManager:
    """섹션 상태와 런타임 동작을 중앙에서 관리한다."""
    def __init__(self):
        """인스턴스의 초기 상태를 구성한다."""
        self._section_variants = None
        self._last_variant_id = 0
        self._on_added_section_fn = None
        self._settings = carb.settings.get_settings()
        purposes = [UsdGeom.Tokens.default_]
        self._bboxcache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), purposes)

        self.refresh()

    def __del__(self):  # pragma: no cover
        """사용한 구독과 리소스를 정리한다."""
        self.destroy()

    def destroy(self):
        """사용한 구독과 리소스를 정리한다."""
        self._settings = None
        self._on_added_section_fn = None
        self._bboxcache = None

    @property
    def section_names(self):
        """해당 함수의 핵심 로직을 수행한다."""
        return list(self._section_variants.keys())

    @property
    def section_count(self):
        """해당 함수의 핵심 로직을 수행한다."""
        return len(self._section_variants) if self._section_variants else 0

    def clear(self):
        """해당 함수의 핵심 로직을 수행한다."""
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
        """현재 상태를 다시 계산하고 갱신한다."""
        self.clear()
        self._stage = omni.usd.get_context().get_stage()
        self._load_section_variants()

    def set_added_section_callback(self, cb: callable):
        """입력값을 내부 상태와 설정에 반영한다."""
        self._on_added_section_fn = cb

    def is_section_enabled(self) -> bool:
        """해당 함수의 핵심 로직을 수행한다."""
        if not self._settings:
            return False
        return self._settings.get_as_bool(SETTING_SECTION_ENABLED)

    def _resolve_ext_id(self) -> str:
        # 런타임에서 extension instance가 있으면 ext_id를 우선 사용하고,
        # 없으면 고정 extension 이름으로 fallback 한다.
        """해당 함수의 핵심 로직을 수행한다."""
        try:
            from .. import get_instance

            inst = get_instance()
            if inst and getattr(inst, "_ext_id", None):
                return inst._ext_id
        except Exception:
            pass
        return "morph.hytwin_section_extension"

    def run_section_runtime(self, ext_id: str = None, show_gizmo: bool = True) -> bool:
        """런타임 실행 경로를 시작한다."""
        ext_id = (ext_id or "").strip() or self._resolve_ext_id()

        self._settings.set_bool(SETTING_SECTION_ENABLED, True)
        self._settings.set_bool(SETTING_SECTION_MANIPULATOR, True)

        if self.section_count == 0:
            self.add_section()

        from ..tool import SectionTool

        SectionTool().set_visibility(True, ext_id)
        if show_gizmo:
            SectionTool().show_section_gizmo(True)
        return True

    def run_section_only(self, ext_id: str = None) -> bool:
        """런타임 실행 경로를 시작한다."""
        return self.run_section_runtime(ext_id=ext_id, show_gizmo=False)

    def stop_section_only(self, ext_id: str = None) -> bool:
        """실행 중인 런타임 경로를 중지한다."""
        ext_id = (ext_id or "").strip() or self._resolve_ext_id()

        self._settings.set_bool(SETTING_SECTION_MANIPULATOR, False)
        self._settings.set_bool(SETTING_SECTION_ENABLED, False)

        from ..tool import SectionTool

        SectionTool().show_section_gizmo(False)
        SectionTool().set_visibility(False, ext_id)
        return True

    def add_section(self):
        """해당 함수의 핵심 로직을 수행한다."""
        with self._get_section_edit_context():

            section = self._get_section_from_widget(is_new=True)
            if section is None:  # pragma: no cover
                carb.log_error("[SectionTool] Failed to get section info!")
                return None


            self._add_section_internal(section)

            if self._on_added_section_fn:
                self._on_added_section_fn(section["name"])

            self.save_section(section["name"])

    def align_widget(self, align, apply_to_all_scenes: bool = True, scene_index: int = None):
        """선택한 축 기준으로 섹션을 정렬한다."""
        if align == WidgetAlignment.X:
            rotation = Gf.Rotation(Gf.Vec3d(0, 1, 0), 90) * Gf.Rotation(Gf.Vec3d(1, 0, 0), 90)
        elif align == WidgetAlignment.Y:
            rotation = Gf.Rotation(Gf.Vec3d(1, 0, 0), -90) * Gf.Rotation(Gf.Vec3d(0, 1, 0), -90)
        else:
            rotation = Gf.Rotation().SetIdentity()

        self._apply_rotation_to_widget_transforms(
            rotation, apply_to_all_scenes=apply_to_all_scenes, scene_index=scene_index
        )

    def rotate_widget(self, align, angle, apply_to_all_scenes: bool = True, scene_index: int = None):
        """현재 축과 각도 설정으로 섹션을 회전한다."""
        self._apply_incremental_rotation_to_widget_transforms(align=align, angle=angle, apply_to_all_scenes=apply_to_all_scenes, scene_index=scene_index)

    def set_widget_position(self, position):
        """입력값을 내부 상태와 설정에 반영한다."""
        with self._get_section_edit_context():
            transform_attr = self._resolve_target_transform_attr()
            if transform_attr:
                transform = transform_attr.Get()
                transform.SetTranslateOnly(position)
                transform_attr.Set(transform)

    def _is_section_widget_path(self, prim_path: str) -> bool:
        """해당 함수의 핵심 로직을 수행한다."""
        return bool(prim_path and str(prim_path).endswith(SECTION_PRIM_PATH))

    def _get_selected_section_transform_attr(self):
        """현재 상태에서 필요한 값을 조회해 반환한다."""
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
        # 우선순위:
        # 1) 현재 선택된 Section_Tool_Object
        # 2) 캐시된 기본 transform attribute
        """해당 함수의 핵심 로직을 수행한다."""
        selected_attr = self._get_selected_section_transform_attr()
        if selected_attr:
            return selected_attr

        if self._section_transform_attr:
            return self._section_transform_attr

        if self.get_section_widget_prim(create_if_not_exist=True):
            return self._section_transform_attr
        return None

    def set_widget_position_from_prim_path(self, prim_path: str) -> bool:
        """입력값을 내부 상태와 설정에 반영한다."""
        if not prim_path:
            carb.log_warn("[SectionTool] set_widget_position_from_prim_path: empty prim path")
            return False

        if not self._stage:
            self._stage = omni.usd.get_context().get_stage()
        if not self._stage:
            carb.log_warn("[SectionTool] set_widget_position_from_prim_path: stage is not ready")
            return False

        # 대상 transform 확보(선택된 섹션 우선, 없으면 기본 섹션).
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
        # 1순위: 월드 바운딩박스 중심점
        """현재 상태에서 필요한 값을 조회해 반환한다."""
        try:
            bound = self._bboxcache.ComputeWorldBound(prim).ComputeAlignedRange()
            if bound and not bound.IsEmpty():
                return bound.GetMidpoint()
        except Exception:  # pragma: no cover
            pass

        # 2순위: 월드 트랜스폼 위치
        try:
            xform = UsdGeom.Xformable(prim)
            matrix = xform.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            return matrix.ExtractTranslation()
        except Exception:  # pragma: no cover
            return None

    def _get_next_available_name(self):
        """현재 상태에서 필요한 값을 조회해 반환한다."""
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
        """해당 함수의 핵심 로직을 수행한다."""
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
        """입력값을 내부 상태와 설정에 반영한다."""
        with self._get_section_edit_context():
            if not self._widget_prim:
                return
            if self._widget_prim.HasAttribute(name):
                attribute = self._widget_prim.GetAttribute(name)
            else:
                attribute = self._widget_prim.CreateAttribute(name, type_name)
            attribute.Set(value)

    def _get_section_attribute(self, name, default):
        """현재 상태에서 필요한 값을 조회해 반환한다."""
        with self._get_section_edit_context():
            if self._widget_prim and self._widget_prim.HasAttribute(name):
                attribute = self._widget_prim.GetAttribute(name)
                value = attribute.Get()
                return value

            return default

    # TODO: Suspect unused code; remove if so
    def _clear_section_attribute(self, name):  # pragma: no cover
        """해당 함수의 핵심 로직을 수행한다."""
        if self._widget_prim.HasAttribute(name):
            attribute = self._widget_prim.GetAttribute(name)
            attribute.Clear()

    def _set_light(self, value):
        """입력값을 내부 상태와 설정에 반영한다."""
        self._set_section_attribute(ATTR_SECTION_LIGHT, value, Sdf.ValueTypeNames.Bool)

    # TODO: Suspect unused code; remove if so
    def _get_light(self):  # pragma: no cover
        """현재 상태에서 필요한 값을 조회해 반환한다."""
        return self._get_section_attribute(ATTR_SECTION_LIGHT, False)

    # TODO: Suspect unused code; remove if so
    def _clear_light(self):  # pragma: no cover
        """해당 함수의 핵심 로직을 수행한다."""
        self._clear_section_attribute(ATTR_SECTION_LIGHT)

    def set_direction(self, value):
        """입력값을 내부 상태와 설정에 반영한다."""
        self._set_section_attribute(ATTR_SECTION_DIRECTION, value, Sdf.ValueTypeNames.Bool)

    def get_direction(self):
        """현재 상태에서 필요한 값을 조회해 반환한다."""
        return self._get_section_attribute(ATTR_SECTION_DIRECTION, DEFAULT_SECTION_TOP)

    def _create_section_spawn_point(self) -> Gf.Vec3d:
        """해당 함수의 핵심 로직을 수행한다."""

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
        """해당 함수의 핵심 로직을 수행한다."""
        with self._get_section_edit_context():
            self._clear_section_attribute(ATTR_SECTION_DIRECTION)

    def get_transform_attr(self, viewport_key: str = None):
        """현재 상태에서 필요한 값을 조회해 반환한다."""
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
        """해당 함수의 핵심 로직을 수행한다."""
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
        """해당 함수의 핵심 로직을 수행한다."""
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

            vset.SetVariantSelection(name)
            with vset.GetVariantEditContext():
                self.set_direction(section["direction"])
                self._set_light(section["light"])
                self._section_transform_attr = self._widget_prim.GetAttribute(ATTR_SECTION_TRANSFORM)
                self._section_transform_attr.Set(section["transform"])

            return section

    def _get_section_from_widget(self, name=None, is_new: bool = False):
        """현재 상태에서 필요한 값을 조회해 반환한다."""
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
        """현재 상태에서 필요한 값을 조회해 반환한다."""
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
        """해당 함수의 핵심 로직을 수행한다."""
        safe = re.sub(r"[^a-zA-Z0-9_]", "_", str(viewport_key or "default"))
        return safe.strip("_") or "default"

    def _get_section_widget_path(self, section_tool_path: str, viewport_key: str = None) -> str:
        """현재 상태에서 필요한 값을 조회해 반환한다."""
        if not viewport_key:
            return section_tool_path + SECTION_PRIM_PATH
        safe_key = self._sanitize_viewport_key(viewport_key)
        return f"{section_tool_path}/{safe_key}{SECTION_PRIM_PATH}"

    def get_section_widget_prim(self, create_if_not_exist=False, viewport_key: str = None):
        """현재 상태에서 필요한 값을 조회해 반환한다."""
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
        """현재 상태에서 필요한 값을 조회해 반환한다."""
        with self._get_section_edit_context():
            if self._stage.HasDefaultPrim():
                defaultPath = self._stage.GetDefaultPrim().GetPath().pathString
                old_path = defaultPath + SECTION_TOOL_PATH
                if self._stage.GetPrimAtPath(old_path):
                    return old_path
            return SECTION_TOOL_PATH

    def _get_section_edit_context(self):
        """현재 상태에서 필요한 값을 조회해 반환한다."""
        stage = omni.usd.get_context().get_stage()
        sect_layer = self._get_section_layer()
        return Usd.EditContext(stage, sect_layer)

    def _get_section_layer(self):
        """현재 상태에서 필요한 값을 조회해 반환한다."""
        settings = carb.settings.get_settings()
        use_session_layer = settings.get(SETTING_SECTION_USE_SESSION_LAYER)
        stage = omni.usd.get_context().get_stage()
        if bool(use_session_layer):
            return stage.GetSessionLayer()
        else:  # pragma: no cover
            return stage.GetRootLayer()

    def get_center_of_prims(self, prim_paths: list):
        """현재 상태에서 필요한 값을 조회해 반환한다."""
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

    def move_scene_models_to_placeholder_prim_center(self) -> bool:
        """
        SectionTool의 모든 scene model 위치를 임의 prim 중심으로 이동한다.
        """
        if not self._stage:
            self._stage = omni.usd.get_context().get_stage()
        if not self._stage:
            carb.log_warn("[SectionTool] move_scene_models_to_placeholder_prim_center: stage is not ready")
            return False

        from ..tool import SectionTool

        moved_any = False
        for scene in SectionTool().scenes:
            viewport_key = getattr(scene, "_viewport_key", None)

            # TODO(사용자 지정): scene/viewport 기준으로 대상 prim 경로를 선택하세요.
            # 예시:
            # if viewport_key == "id:123":
            #     target_prim_path = "/World/Cube_A"
            # else:
            #     target_prim_path = "/World/Cube_B"
            target_prim_path = "/World/PlaceholderPrim"

            # TODO(사용자 지정): 필요 시 기대 좌표 예시
            # 예시 중심 좌표: (0.0, 100.0, 0.0)
            prim = self._stage.GetPrimAtPath(target_prim_path)
            if not prim or not prim.IsValid():
                carb.log_warn(
                    "[SectionTool] move_scene_models_to_placeholder_prim_center: "
                    f"invalid prim path for viewport({viewport_key}): {target_prim_path}"
                )
                continue

            center = self._get_prim_world_center(prim)
            if center is None:
                carb.log_warn(
                    "[SectionTool] move_scene_models_to_placeholder_prim_center: "
                    f"failed to compute center for viewport({viewport_key}): {target_prim_path}"
                )
                continue

            model = getattr(scene, "_section_model", None)
            if not model:
                continue
            try:
                transform = Gf.Matrix4d()
                transform.SetTranslateOnly(center)
                model.set_floats(model.get_item("transform"), transform)
                moved_any = True
            except Exception as exc:  # pragma: no cover
                carb.log_warn(
                    f"[SectionTool] move_scene_models_to_placeholder_prim_center: failed to update scene model: {exc}"
                )

        if not moved_any:
            carb.log_warn("[SectionTool] move_scene_models_to_placeholder_prim_center: no scene model was updated")
            return False

        carb.log_info("[SectionTool] move_scene_models_to_placeholder_prim_center: scene model update completed")
        return True

    def move_scenes_in_connected_prim_range(self, dir: str, value: float) -> bool:
        """
        scenes를 순회하며 각 scene에 연결된 prim의 중심 기준 축 범위(0~1) 위치로 이동한다.
        dir: "x" | "y" | "z"
        value: 0.0 ~ 1.0
        """
        axis_map = {"x": 0, "y": 1, "z": 2}
        axis = axis_map.get(str(dir or "").lower())
        if axis is None:
            carb.log_warn(f"[SectionTool] move_scenes_in_connected_prim_range: invalid dir: {dir}")
            return False

        if not self._stage:
            self._stage = omni.usd.get_context().get_stage()
        if not self._stage:
            carb.log_warn("[SectionTool] move_scenes_in_connected_prim_range: stage is not ready")
            return False

        t = max(0.0, min(1.0, float(value)))

        from ..tool import SectionTool

        scenes = SectionTool().scenes
        if not scenes:
            carb.log_warn("[SectionTool] move_scenes_in_connected_prim_range: no scenes")
            return False

        moved_any = False
        last_center = None

        for scene in scenes:
            # TODO(사용자 지정): scene -> 연결 prim 조회 로직을 여기에 추가하세요.
            # 예시:
            # prim = self._stage.GetPrimAtPath("/World/YourPrim")
            prim = None
            if not prim or not prim.IsValid():
                continue

            center = self._get_prim_world_center(prim)
            if center is None:
                continue

            try:
                bound = self._bboxcache.ComputeWorldBound(prim).ComputeAlignedRange()
            except Exception:  # pragma: no cover
                continue

            if not bound or bound.IsEmpty():
                continue

            axis_min = bound.GetMin()[axis]
            axis_max = bound.GetMax()[axis]
            target_axis = axis_min + (axis_max - axis_min) * t

            target = Gf.Vec3d(center[0], center[1], center[2])
            target[axis] = target_axis

            model = getattr(scene, "_section_model", None)
            if not model:
                continue

            try:
                transform = Gf.Matrix4d()
                transform.SetTranslateOnly(target)
                model.set_floats(model.get_item("transform"), transform)
                moved_any = True
                last_center = target
            except Exception as exc:  # pragma: no cover
                carb.log_warn(f"[SectionTool] move_scenes_in_connected_prim_range: failed to update scene model: {exc}")

        if not moved_any:
            carb.log_warn("[SectionTool] move_scenes_in_connected_prim_range: no scene model was updated")
            return False

        if last_center is not None:
            self.set_widget_position(last_center)

        carb.log_info("[SectionTool] move_scenes_in_connected_prim_range: scene model update completed")
        return True

    def _iter_scene_transform_attrs(self):
        """현재 열려 있는 모든 scene의 transform attribute를 순회한다."""
        from ..tool import SectionTool

        attrs = []
        seen = set()
        for scene in SectionTool().scenes:
            viewport_key = getattr(scene, "_viewport_key", None)
            attr = self.get_transform_attr(viewport_key=viewport_key)
            if not attr:
                continue
            key = str(attr.GetPath())
            if key in seen:
                continue
            seen.add(key)
            attrs.append(attr)
        return attrs

    def _iter_target_transform_attrs(self, apply_to_all_scenes: bool, scene_index: int = None):
        """요청 범위(전체 scene/단일 대상)에 맞는 transform attribute 목록을 반환한다."""
        if apply_to_all_scenes:
            attrs = self._iter_scene_transform_attrs()
            if attrs:
                return attrs
        elif scene_index is not None:
            attr = self._get_scene_transform_attr_by_index(scene_index)
            if attr:
                return [attr]
            carb.log_warn(f"[SectionTool] invalid scene index: {scene_index}")

        transform_attr = self._resolve_target_transform_attr()
        return [transform_attr] if transform_attr else []

    def _apply_rotation_to_widget_transforms(self, rotation: Gf.Rotation, apply_to_all_scenes: bool = True, scene_index: int = None):
        """대상 widget transform들에 절대 회전을 적용한다."""
        with self._get_section_edit_context():
            for transform_attr in self._iter_target_transform_attrs(apply_to_all_scenes, scene_index=scene_index):
                transform = transform_attr.Get()
                transform.SetRotateOnly(rotation)
                transform_attr.Set(transform)

    def _apply_incremental_rotation_to_widget_transforms(self, align, angle, apply_to_all_scenes: bool = True, scene_index: int = None):
        """대상 widget transform들에 축 기준 증분 회전을 적용한다."""
        with self._get_section_edit_context():
            for transform_attr in self._iter_target_transform_attrs(apply_to_all_scenes, scene_index=scene_index):
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

    def _get_scene_transform_attr_by_index(self, scene_index: int):
        """scene index 기준으로 단일 scene의 transform attribute를 반환한다."""
        if scene_index is None or scene_index < 0:
            return None

        from ..tool import SectionTool

        scenes = SectionTool().scenes
        if scene_index >= len(scenes):
            return None

        viewport_key = getattr(scenes[scene_index], "_viewport_key", None)
        return self.get_transform_attr(viewport_key=viewport_key)
