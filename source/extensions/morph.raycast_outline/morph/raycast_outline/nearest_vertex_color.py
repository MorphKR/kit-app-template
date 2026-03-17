from __future__ import annotations

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
