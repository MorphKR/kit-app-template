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
from pxr import Sdf, UsdGeom, UsdShade

from ..color_sampling import sample_hit_texture_color


# -----------------------------------------------------------------------------
# 이벤트 핸들러 타입
# -----------------------------------------------------------------------------
HoverHandler = Callable[[Optional[str]], None]


# -----------------------------------------------------------------------------
# Raycast 유틸리티 (본 모듈 내부)
# -----------------------------------------------------------------------------
def _coords_in_viewport(viewport_api, ndc_coords: Sequence[float]) -> bool:
    """
    NDC 좌표가 "현재 활성 뷰포트 텍스처 영역" 안에 들어오는지 확인합니다.

    - 목적: 뷰포트 밖(예: UI 영역)에서 발생한 마우스 입력을 raycast로 넘기지 않기
    - 구현: `map_ndc_to_texture()`의 반환값 마지막 슬롯이 None인지로 유효성을 판단
    """
    result = viewport_api.map_ndc_to_texture(ndc_coords)
    return result[-1] is not None if result else False


def _generate_picking_ray(
    viewport_api, ndc_location: Sequence[float]
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    """
    NDC 마우스 위치에서 픽킹 레이(origin, direction)를 생성합니다.

    - 입력: NDC (x, y) in [-1, 1] 범위, z는 near/far로 -1/+1을 사용
    - 변환: (View * Projection)^(-1)로 near/far 점을 월드로 역변환
    - 결과: origin = near점, direction = far - near (정규화)
    """
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


def _get_material_diffuse_color( *,viewport_api, prim,) -> Optional[Tuple[float, float, float, float]]:
    try:
        binding_api = UsdShade.MaterialBindingAPI(prim)
        material = binding_api.ComputeBoundMaterial()[0]
        shader = UsdShade.Shader(UsdShade.Material(material).ComputeSurfaceSource()[0])
        diffuse = shader.GetInput("diffuseColor").Get()
        r, g, b = diffuse[:3]
        a = diffuse[3] if len(diffuse) > 3 else 1.0
        return (float(r), float(g), float(b), float(a))
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
                hit_pos = getattr(result, "hit_position", None)
                if hit_pos is not None:
                    try:
                        x, y, z = float(hit_pos[0]), float(hit_pos[1]), float(hit_pos[2])
                        # print(f"[morph.raycast_outline] hover hit: {prim_path} @ ({x:.6f}, {y:.6f}, {z:.6f})")
                        # `prim_path`를 통해 USD `prim`을 1회만 조회한 뒤,
                        # `BasisCurves`면 diffuseColor를 읽고, 아니면 Mesh 텍스처 샘플링으로 폴백합니다.
                        usd_ctx = getattr(viewport_api, "usd_context", None)
                        stage = usd_ctx.get_stage() if usd_ctx else None
                        prim = stage.GetPrimAtPath(Sdf.Path(prim_path)) if stage else None

                        if prim and UsdGeom.BasisCurves(prim):
                            tex_rgba = _get_material_diffuse_color(
                                viewport_api=viewport_api,
                                prim=prim,
                            )
                            print(f"[morph.raycast_outline] basis curves material diffuse color: {tex_rgba}")
                        else:
                            face_index = int(getattr(result, "primitive_id", -1))
                            tex_rgba = sample_hit_texture_color(
                                viewport_api=viewport_api,
                                prim_path=prim_path,
                                hit_pos_world=(x, y, z),
                                face_index=face_index,
                            )
                            print(f"[morph.raycast_outline] mesh texture color: {tex_rgba}")

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
