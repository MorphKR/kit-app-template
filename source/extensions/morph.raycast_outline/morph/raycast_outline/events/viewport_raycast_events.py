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
from pxr import Gf, Sdf, UsdGeom, UsdShade


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


def _list_to_gf_matrix4d(data: Sequence[float]) -> Gf.Matrix4d:
    """
    viewport/usd_context가 반환하는 "flattened 4x4 list(길이 16)"를 `Gf.Matrix4d`로 변환합니다.

    - `compute_path_world_transform()`는 보통 길이 16 list를 반환합니다.
    - 길이가 16이 아니면 조용히 잘못된 변환을 만들지 않도록 예외를 던집니다.
    """
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
    # 주석 처리(비활성): nearest-vertex 기반 컬러 샘플링
    #
    # 원래 의도:
    # - hit 월드 좌표와 Mesh의 전체 vertex(Points) 사이 거리로 nearest vertex index를 찾고
    # - `primvars:displayColor`(vertex interpolation) 또는 `displayColor`로 색을 읽는 방식
    #
    # 현재는 요청에 따라 아래 파이프라인으로 대체됨:
    # hit face → triangle → barycentric → UV → texture pixel sample
    return None


def _dominant_axis(v: Gf.Vec3d) -> int:
    """
    벡터 v에서 절대값이 가장 큰 축 인덱스를 반환합니다. (0=x, 1=y, 2=z)

    - 목적: 3D triangle 위의 점 포함 여부를 barycentric으로 계산할 때,
      수치적으로 안정적인 2D 평면으로 투영하기 위해 "drop"할 축을 선택합니다.
    """
    ax = abs(float(v[0]))
    ay = abs(float(v[1]))
    az = abs(float(v[2]))
    if ax >= ay and ax >= az:
        return 0
    if ay >= ax and ay >= az:
        return 1
    return 2


def _barycentric_2d(
    p: Tuple[float, float],
    a: Tuple[float, float],
    b: Tuple[float, float],
    c: Tuple[float, float],
) -> Optional[Tuple[float, float, float]]:
    """
    2D 삼각형 (a,b,c)와 점 p에 대한 barycentric (u,v,w)를 계산합니다.

    - 반환: u+v+w=1
    - u,v,w가 모두 0~1 범위(약간의 epsilon 허용)면 삼각형 내부(또는 경계)로 간주 가능
    - 분모가 0(퇴화 삼각형)인 경우 None
    """
    (px, py), (ax, ay), (bx, by), (cx, cy) = p, a, b, c
    v0x, v0y = bx - ax, by - ay
    v1x, v1y = cx - ax, cy - ay
    v2x, v2y = px - ax, py - ay
    den = v0x * v1y - v1x * v0y
    if abs(den) < 1e-12:
        return None
    inv = 1.0 / den
    v = (v2x * v1y - v1x * v2y) * inv
    w = (v0x * v2y - v2x * v0y) * inv
    u = 1.0 - v - w
    return (u, v, w)


def _triangulate_face_vertex_indices(face_vidx: Sequence[int]) -> list[Tuple[int, int, int]]:
    """
    한 face의 vertex index 배열(ngon 포함)을 triangle list로 분해합니다.

    - 전략: triangle fan (v0, vi, v{i+1})
    - 주의: concave polygon에서는 fan 분해가 기하학적으로 정확하지 않을 수 있습니다.
      (일반적인 DCC export mesh는 convex/triangulated인 경우가 많아 실용적으로 사용)
    """
    n = len(face_vidx)
    if n < 3:
        return []
    if n == 3:
        return [(int(face_vidx[0]), int(face_vidx[1]), int(face_vidx[2]))]
    v0 = int(face_vidx[0])
    return [(v0, int(face_vidx[i]), int(face_vidx[i + 1])) for i in range(1, n - 1)]


def _compute_face_corner_range(face_vertex_counts: Sequence[int], face_index: int) -> Optional[Tuple[int, int]]:
    """
    face index → (corner_offset, corner_count)를 계산합니다.

    USD Mesh의 faceVertexIndices는 "전체 face의 corner를 1차원으로 나열"한 배열이므로,
    faceVertexCounts의 누적합으로 해당 face의 시작 오프셋을 구합니다.
    """
    if face_index < 0 or face_index >= len(face_vertex_counts):
        return None
    offset = 0
    for i in range(face_index):
        offset += int(face_vertex_counts[i])
    return (offset, int(face_vertex_counts[face_index]))


def _get_face_corner_uvs(
    *,
    mesh: UsdGeom.Mesh,
    face_corner_offset: int,
    face_corner_count: int,
    vertex_indices_for_face: Sequence[int],
) -> Optional[list[Tuple[float, float]]]:
    """
    hit face의 corner 순서에 맞는 UV 리스트를 반환합니다.

    - primvar 이름: 관례적으로 `st`를 사용 (USD Preview Surface 파이프라인에서 흔함)
    - interpolation 처리:
      - faceVarying: UV가 corner(=faceVertexIndices)와 1:1 대응 → offset으로 슬라이스
      - vertex: UV가 vertex index와 대응 → vertex index로 인덱싱
      - uniform/constant 등: 값 하나로 간주하여 corner 수만큼 복제
    """
    pv = UsdGeom.PrimvarsAPI(mesh.GetPrim()).GetPrimvar("st")
    if not pv or not pv.IsDefined():
        return None
    vals = pv.Get()
    if not vals:
        return None

    interp = pv.GetInterpolation() or ""
    if interp == UsdGeom.Tokens.faceVarying:
        end = face_corner_offset + face_corner_count
        if end > len(vals):
            return None
        return [(float(uv[0]), float(uv[1])) for uv in vals[face_corner_offset:end]]
    if interp == UsdGeom.Tokens.vertex:
        uvs: list[Tuple[float, float]] = []
        for vi in vertex_indices_for_face:
            v_int = int(vi)
            if v_int >= len(vals):
                return None
            uv = vals[v_int]
            uvs.append((float(uv[0]), float(uv[1])))
        return uvs

    uv0 = vals[0]
    return [(float(uv0[0]), float(uv0[1])) for _ in range(face_corner_count)]


def _resolve_diffuse_texture_asset_path(prim) -> Optional[str]:
    """
    prim에 바인딩된 머티리얼에서 diffuse/albedo/baseColor 텍스처 경로를 best-effort로 찾습니다.

    처리 흐름(USD Preview Surface 계열을 가정):
    - MaterialBindingAPI.ComputeBoundMaterial()로 바운드 머티리얼 탐색
    - material.ComputeSurfaceSource()로 surface shader(보통 UsdPreviewSurface) 획득
    - shader.inputs:diffuseColor(or albedo/baseColor)의 연결 upstream을 따라가
    - 연결된 UsdUVTexture shader의 inputs:file asset을 읽음

    반환값:
    - 성공: asset의 resolvedPath/path/문자열 중 가능한 것을 str로 반환
    - 실패: None
    """
    try:
        binding_api = UsdShade.MaterialBindingAPI(prim)
        material, _ = binding_api.ComputeBoundMaterial()
        if not material:
            return None

        try:
            _out, shader, _name = material.ComputeSurfaceSource()
        except Exception:
            shader = None
        if not shader:
            return None

        diffuse_in = shader.GetInput("diffuseColor") or shader.GetInput("albedo") or shader.GetInput("baseColor")
        if not diffuse_in:
            return None

        src = diffuse_in.GetConnectedSource()
        if not src or len(src) < 2:
            return None

        tex_prim = src[0].GetPrim()
        if not tex_prim or not tex_prim.IsValid():
            return None

        tex_shader = UsdShade.Shader(tex_prim)
        if not tex_shader:
            return None

        file_in = tex_shader.GetInput("file")
        if not file_in:
            return None

        asset = file_in.Get()
        asset_path = getattr(asset, "resolvedPath", None) or getattr(asset, "path", None) or str(asset)
        return str(asset_path) if asset_path else None
    except Exception:
        return None


def _load_image_rgba_u8(path: str):
    """
    파일 경로의 이미지를 RGBA로 로드합니다.

    - 현재 구현은 Pillow(PIL)에 의존합니다.
    - PIL이 없거나 파일 접근 실패 시 None
    """
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return None
    try:
        return Image.open(path).convert("RGBA")
    except Exception:
        return None


def _sample_texture_rgba(image_rgba, uv: Tuple[float, float]) -> Optional[Tuple[float, float, float, float]]:
    """
    이미지에서 UV(0~1)를 이용해 가장 가까운 픽셀을 샘플링해 RGBA(float 0~1)를 반환합니다.

    - wrap: repeat (u, v의 소수부만 사용)
    - 좌표계: USD UV는 보통 v-up, 이미지 좌표는 y-down → (1 - v)로 뒤집음
    - 필터: nearest(라운드)
    """
    if image_rgba is None:
        return None
    try:
        w, h = image_rgba.size
        if w <= 0 or h <= 0:
            return None
        u, v = float(uv[0]), float(uv[1])
        u = u - float(int(u))
        v = v - float(int(v))
        x = int(max(0, min(w - 1, round(u * (w - 1)))))
        y = int(max(0, min(h - 1, round((1.0 - v) * (h - 1)))))
        r, g, b, a = image_rgba.getpixel((x, y))
        return (float(r) / 255.0, float(g) / 255.0, float(b) / 255.0, float(a) / 255.0)
    except Exception:
        return None


def _sample_hit_texture_color(
    *,
    viewport_api,
    prim_path: str,
    hit_pos_world: Sequence[float],
    face_index: int,
) -> Optional[Tuple[float, float, float, float]]:
    """
    Raycast hit 정보를 이용해 "텍스처 픽셀 색"을 추정/샘플링합니다.

    입력:
    - prim_path: hit된 USD prim path (Mesh여야 함)
    - hit_pos_world: raycast hit 위치(월드 좌표)
    - face_index: raycast 결과의 face id (여기서는 result.primitive_id를 사용)

    단계:
    1) Mesh topology( faceVertexCounts / faceVertexIndices )로 hit face의 corner 범위를 구함
    2) face를 triangle로 분해(fan)하고, 각 triangle에 대해
       - triangle normal의 dominant axis를 drop하여 2D 투영
       - barycentric으로 hit 점이 triangle 내부인지 판정
    3) triangle의 (u,v,w) barycentric을 corner/vertex UV에 적용해 hit UV를 보간
    4) 머티리얼 네트워크에서 diffuse 텍스처 파일을 찾고, UV로 픽셀 샘플링

    반환:
    - 성공: (r,g,b,a) float(0~1)
    - 실패: None (UV/텍스처/머티리얼/토폴로지 중 하나라도 부족하면)
    """
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

    face_vertex_counts = mesh.GetFaceVertexCountsAttr().Get()
    face_vertex_indices = mesh.GetFaceVertexIndicesAttr().Get()
    points = mesh.GetPointsAttr().Get()
    if not face_vertex_counts or not face_vertex_indices or not points:
        return None

    corner_range = _compute_face_corner_range(face_vertex_counts, int(face_index))
    if not corner_range:
        return None
    face_corner_offset, face_corner_count = corner_range
    face_vidx = face_vertex_indices[face_corner_offset : face_corner_offset + face_corner_count]
    if len(face_vidx) < 3:
        return None

    corner_uvs = _get_face_corner_uvs(
        mesh=mesh,
        face_corner_offset=face_corner_offset,
        face_corner_count=face_corner_count,
        vertex_indices_for_face=face_vidx,
    )
    if not corner_uvs or len(corner_uvs) != len(face_vidx):
        return None

    tex_path = _resolve_diffuse_texture_asset_path(prim)
    if not tex_path:
        return None
    img = _load_image_rgba_u8(tex_path)
    if img is None:
        return None

    xform_list = usd_ctx.compute_path_world_transform(prim_path) if usd_ctx else None
    xform = _list_to_gf_matrix4d(xform_list) if xform_list else Gf.Matrix4d(1.0)

    # ---- 3D -> 2D 포함 판정 준비 ----
    # face에 포함된 vertex들의 "월드 좌표"를 캐싱합니다.
    # (points는 로컬 공간이므로 hit_pos_world와 비교/투영하려면 월드 변환이 필요)
    world_pos_cache: dict[int, Gf.Vec3d] = {}
    for vi in set(int(v) for v in face_vidx):
        p = points[int(vi)]
        world_pos_cache[int(vi)] = xform.Transform(Gf.Vec3d(float(p[0]), float(p[1]), float(p[2])))

    # hit point도 월드 공간 벡터로 준비
    hp = Gf.Vec3d(float(hit_pos_world[0]), float(hit_pos_world[1]), float(hit_pos_world[2]))
    tris = _triangulate_face_vertex_indices(face_vidx)
    if not tris:
        return None

    # ---- UV 준비 ----
    # corner_uvs는 "face corner 순서"에 대응합니다.
    #
    # 여기서는 triangle의 (vertex index)만 알 수 있으므로,
    # vertex index -> uv로 매핑이 필요합니다.
    #
    # - vertex/constant/uniform interpolation: vertex index 기반 매핑이 자연스럽습니다.
    # - faceVarying interpolation: 같은 vertex index가 여러 corner에서 다른 uv를 가질 수 있는데,
    #   본 구현은 단순화를 위해 "처음 등장한 corner의 uv를 대표값"으로 사용합니다(best-effort).
    vi_to_uv: dict[int, Tuple[float, float]] = {}
    for corner_i, vi in enumerate(face_vidx):
        v_int = int(vi)
        if v_int not in vi_to_uv:
            vi_to_uv[v_int] = corner_uvs[corner_i]

    # ---- triangle 선택 + barycentric ----
    # hit face를 triangle로 분해했으므로(triangle fan),
    # 각 triangle에 대해 hit 점이 내부인지 barycentric으로 검사합니다.
    #
    # barycentric은 2D에서 계산하므로,
    # triangle normal의 dominant axis를 drop해 2D로 투영합니다.
    eps = 1e-6
    for i0, i1, i2 in tris:
        p0 = world_pos_cache[i0]
        p1 = world_pos_cache[i1]
        p2 = world_pos_cache[i2]
        n = Gf.Cross(p1 - p0, p2 - p0)
        if n.GetLength() < eps:
            continue
        drop = _dominant_axis(n)

        def proj(vv: Gf.Vec3d) -> Tuple[float, float]:
            if drop == 0:
                return (float(vv[1]), float(vv[2]))
            if drop == 1:
                return (float(vv[0]), float(vv[2]))
            return (float(vv[0]), float(vv[1]))

        bc = _barycentric_2d(proj(hp), proj(p0), proj(p1), proj(p2))
        if bc is None:
            continue
        bu, bv, bw = bc
        # epsilon을 약간 허용해 경계/수치오차 케이스도 통과시키는 쪽으로 처리
        if (
            bu >= -1e-4
            and bv >= -1e-4
            and bw >= -1e-4
            and bu <= 1.0 + 1e-4
            and bv <= 1.0 + 1e-4
            and bw <= 1.0 + 1e-4
        ):
            uv0 = vi_to_uv.get(i0)
            uv1 = vi_to_uv.get(i1)
            uv2 = vi_to_uv.get(i2)
            if uv0 is None or uv1 is None or uv2 is None:
                return None
            # ---- UV 보간 ----
            # triangle의 3개 꼭짓점 UV를 barycentric으로 보간하여 hit UV를 얻습니다.
            hit_u = bu * uv0[0] + bv * uv1[0] + bw * uv2[0]
            hit_v = bu * uv0[1] + bv * uv1[1] + bw * uv2[1]
            # ---- 텍스처 샘플링 ----
            # 보간된 hit UV로 텍스처에서 픽셀을 샘플링합니다.
            return _sample_texture_rgba(img, (hit_u, hit_v))

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
                        face_index = int(getattr(result, "primitive_id", -1))
                        tex_rgba = _sample_hit_texture_color(
                            viewport_api=viewport_api,
                            prim_path=prim_path,
                            hit_pos_world=(x, y, z),
                            face_index=face_index,
                        )
                        if tex_rgba is not None:
                            r, g, b, a = tex_rgba
                            print(
                                "[morph.raycast_outline] texture sample RGBA: "
                                f"({r:.6f}, {g:.6f}, {b:.6f}, {a:.6f})"
                            )
                        else:
                            print("[morph.raycast_outline] texture sample RGBA: <none>")
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
