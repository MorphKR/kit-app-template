# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

"""
뷰포트 Raycast 이벤트 모듈 (독립 모듈)

Hover, Click 등 뷰포트 마우스 이벤트를 등록하고, raycast를 수행하여
prim 감지 후 핸들러에 결과를 디스패치합니다.
raycast 관련 로직(NDC→레이 변환, 좌표 검사)을 모두 포함합니다.

이 모듈은 OutlineOverlay, USD 등에 종속되지 않습니다.
핸들러 등록은 호출 측(extension, overlay 등)에서 수행합니다.
"""

from typing import Callable, List, Optional, Sequence, Tuple

import omni.kit.raycast.query
from omni.ui import scene as sc
from pxr import Gf, Sdf, UsdGeom


# -----------------------------------------------------------------------------
# 이벤트 핸들러 타입
# -----------------------------------------------------------------------------
HoverHandler = Callable[[Optional[str]], None]


# -----------------------------------------------------------------------------
# Raycast 유틸리티 (본 모듈 내부)
# -----------------------------------------------------------------------------
def _coords_in_viewport(viewport_api, ndc_coords: Sequence[float]) -> bool:
    """NDC 좌표가 뷰포트 내에 있는지 확인합니다."""
    result = viewport_api.map_ndc_to_texture(ndc_coords)
    return result[-1] is not None if result else False


def _generate_picking_ray(
    viewport_api, ndc_location: Sequence[float]
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    """NDC 마우스 위치에서 픽킹 레이(origin, direction)를 생성합니다."""
    ndc_near = (ndc_location[0], ndc_location[1], -1)
    ndc_far = (ndc_location[0], ndc_location[1], 1)
    view = viewport_api.view
    proj = viewport_api.projection
    view_proj_inv = (view * proj).GetInverse()

    origin = view_proj_inv.Transform(ndc_near)
    far_pt = view_proj_inv.Transform(ndc_far)
    direction = far_pt - origin
    direction.Normalize()

    return (
        (origin[0], origin[1], origin[2]),
        (direction[0], direction[1], direction[2]),
    )


def _list_to_gf_matrix4d(data: Sequence[float]) -> Gf.Matrix4d:
    """길이 16의 1차원 시퀀스를 `pxr.Gf.Matrix4d`로 변환합니다."""
    if len(data) != 16:
        raise RuntimeError("Gf.Matrix4d needs 16 numbers to initialize")
    return Gf.Matrix4d(
        data[0],
        data[1],
        data[2],
        data[3],
        data[4],
        data[5],
        data[6],
        data[7],
        data[8],
        data[9],
        data[10],
        data[11],
        data[12],
        data[13],
        data[14],
        data[15],
    )


def _get_nearest_vertex_color(
    *,
    viewport_api,
    prim_path: str,
    hit_pos_world: Sequence[float],
) -> Optional[Tuple[float, float, float, float]]:
    """
    충돌한 prim의 Mesh에서 hit 위치와 가장 가까운 vertex를 찾고,
    해당 vertex의 color(RGBA)를 반환합니다.

    - vertex color는 우선 `primvars:displayColor`(vertex interpolation)를 사용합니다.
    - 없거나 vertex가 아니면 `displayColor`/`displayOpacity`(Gprim)로 폴백합니다.
    """
    try:
        usd_ctx = getattr(viewport_api, "usd_context", None)
        stage = usd_ctx.get_stage() if usd_ctx else None
        if not stage:
            return None

        prim = stage.GetPrimAtPath(Sdf.Path(prim_path))
        if not prim or not prim.IsValid():
            return None

        mesh = UsdGeom.Mesh(prim)
        if not mesh:
            return None

        points = mesh.GetPointsAttr().Get()
        if not points:
            return None

        xform_list = usd_ctx.compute_path_world_transform(prim_path) if usd_ctx else None
        xform = _list_to_gf_matrix4d(xform_list) if xform_list else Gf.Matrix4d(1.0)

        hx, hy, hz = float(hit_pos_world[0]), float(hit_pos_world[1]), float(hit_pos_world[2])
        nearest_i = -1
        nearest_d2 = float("inf")

        for i, p in enumerate(points):
            wp = xform.Transform(Gf.Vec3d(float(p[0]), float(p[1]), float(p[2])))
            dx = float(wp[0]) - hx
            dy = float(wp[1]) - hy
            dz = float(wp[2]) - hz
            d2 = dx * dx + dy * dy + dz * dz
            if d2 < nearest_d2:
                nearest_d2 = d2
                nearest_i = i

        if nearest_i < 0:
            return None

        pv = UsdGeom.PrimvarsAPI(prim).GetPrimvar("displayColor")
        if pv and pv.IsDefined():
            interp = pv.GetInterpolation() or ""
            vals = pv.Get()
            if vals:
                if interp == UsdGeom.Tokens.vertex and nearest_i < len(vals):
                    c = vals[nearest_i]
                    return (float(c[0]), float(c[1]), float(c[2]), 1.0)
                c0 = vals[0]
                return (float(c0[0]), float(c0[1]), float(c0[2]), 1.0)

        gprim = UsdGeom.Gprim(prim)
        if gprim:
            dc = gprim.GetDisplayColorAttr().Get()
            if dc:
                c0 = dc[0]
                a = 1.0
                op = gprim.GetDisplayOpacityAttr().Get()
                if op:
                    with_op = op[0]
                    try:
                        a = float(with_op)
                    except Exception:
                        a = 1.0
                return (float(c0[0]), float(c0[1]), float(c0[2]), float(a))

        return None
    except Exception:
        return None


# -----------------------------------------------------------------------------
# 이벤트 컨텍스트
# -----------------------------------------------------------------------------
class ViewportEventContext:
    """
    이벤트/raycast에 필요한 최소 인터페이스.

    viewport_api와 raycast_query를 제공하는 객체가 구현합니다.
    """

    def get_viewport_api(self):
        raise NotImplementedError

    def get_raycast_query(self):
        raise NotImplementedError


# -----------------------------------------------------------------------------
# 이벤트 매니저
# -----------------------------------------------------------------------------
class ViewportEventManager:
    """
    뷰포트 이벤트를 등록하고 처리하는 매니저.

    Gesture(Hover, Click) 발생 시 raycast를 수행하고,
    등록된 핸들러들에게 결과를 전달합니다.
    """

    def __init__(self, context: ViewportEventContext):
        self._context = context
        self._hover_handlers: List[HoverHandler] = []

    def register_hover(self, handler: HoverHandler) -> None:
        if handler not in self._hover_handlers:
            self._hover_handlers.append(handler)

    def unregister_hover(self, handler: HoverHandler) -> None:
        if handler in self._hover_handlers:
            self._hover_handlers.remove(handler)

    def build_screen(self) -> sc.Screen:
        hover_gesture = sc.HoverGesture(
            name="raycast_outline_hover",
            on_changed_fn=self._on_hover_gesture,
        )
        return sc.Screen(gestures=[hover_gesture])

    def _on_hover_gesture(self, sender) -> None:
        viewport_api = self._context.get_viewport_api()
        raycast_query = self._context.get_raycast_query()
        if not viewport_api or not raycast_query:
            return

        ndc_coords = sender.gesture_payload.mouse

        if not _coords_in_viewport(viewport_api, ndc_coords):
            self._dispatch_hover(None)
            return

        def raycast_callback(ray, result: omni.kit.raycast.query.RayQueryResult, *args, **kwargs):
            if result.valid:
                prim_path = result.get_target_usd_path()
                print("[morph.raycast_outline] hover hit: ", result, "\n")
                hit_pos = getattr(result, "hit_position", None)
                if hit_pos is not None:
                    try:
                        x, y, z = float(hit_pos[0]), float(hit_pos[1]), float(hit_pos[2])
                        print(f"[morph.raycast_outline] hover hit: {prim_path} @ ({x:.6f}, {y:.6f}, {z:.6f})")
                        rgba = _get_nearest_vertex_color(
                            viewport_api=viewport_api,
                            prim_path=prim_path,
                            hit_pos_world=(x, y, z),
                        )
                        if rgba is not None:
                            r, g, b, a = rgba
                            print(
                                "[morph.raycast_outline] nearest vertex color: "
                                f"({r:.6f}, {g:.6f}, {b:.6f}, {a:.6f})"
                            )
                        else:
                            print("[morph.raycast_outline] nearest vertex color: <none>")
                    except Exception:
                        print(f"[morph.raycast_outline] hover hit: {prim_path} @ {hit_pos}")
                self._dispatch_hover(prim_path if prim_path else None)
            else:
                self._dispatch_hover(None)

        origin, direction = _generate_picking_ray(viewport_api, ndc_coords)
        ray = omni.kit.raycast.query.Ray(origin, direction) # Omniverse RTX raycast API
        raycast_query.submit_raycast_query(ray, raycast_callback)

    def _dispatch_hover(self, prim_path: Optional[str]) -> None:
        for handler in self._hover_handlers:
            try:
                handler(prim_path)
            except Exception:
                pass
