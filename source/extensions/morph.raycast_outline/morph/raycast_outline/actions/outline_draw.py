# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

"""
Hover 아웃라인 그리기 모듈

prim의 월드 바운딩 박스 실루엣 엣지만 sc.Line으로 그립니다.
이벤트(Hover)에 연결된 동작으로, events 모듈에서 호출됩니다.
"""

from typing import List, Tuple

import omni.usd
from omni.ui import scene as sc

from ..ui.outline_settings import get_outline_color, get_outline_thickness


# -----------------------------------------------------------------------------
# 라인 연장 비율 (조정 가능)
# -----------------------------------------------------------------------------
LINE_EXTEND_RATIO = 0.002


def _extend_line(
    start: Tuple[float, float, float],
    end: Tuple[float, float, float],
    thickness: float,
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    """라인을 양끝으로 연장하여 모서리에서 이어지는 느낌을 줍니다."""
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dz = end[2] - start[2]
    length = (dx * dx + dy * dy + dz * dz) ** 0.5
    if length < 1e-8:
        return (start, end)
    extend_ratio = LINE_EXTEND_RATIO * (thickness / 2.0)
    extend = length * extend_ratio
    inv_len = extend / length
    new_start = (
        start[0] - dx * inv_len,
        start[1] - dy * inv_len,
        start[2] - dz * inv_len,
    )
    new_end = (
        end[0] + dx * inv_len,
        end[1] + dy * inv_len,
        end[2] + dz * inv_len,
    )
    return (new_start, new_end)


def get_bbox_edges(prim_path: str) -> List[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]:
    """prim의 월드 바운딩 박스 12개 엣지를 반환합니다."""
    try:
        ctx = omni.usd.get_context()
        min_pt, max_pt = ctx.compute_path_world_bounding_box(prim_path)
        if min_pt is None or max_pt is None:
            return []
    except Exception:
        return []

    mn = (float(min_pt[0]), float(min_pt[1]), float(min_pt[2]))
    mx = (float(max_pt[0]), float(max_pt[1]), float(max_pt[2]))

    x0, y0, z0 = mn
    x1, y1, z1 = mx

    corners = [
        (x0, y0, z0), (x1, y0, z0), (x0, y1, z0), (x1, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x0, y1, z1), (x1, y1, z1),
    ]
    edges = [
        (0, 1), (2, 3), (4, 5), (6, 7),
        (0, 2), (1, 3), (4, 6), (5, 7),
        (0, 4), (1, 5), (2, 6), (3, 7),
    ]
    return [(corners[a], corners[b]) for a, b in edges]


_EDGE_FACES = [
    (0, 2), (0, 3), (1, 2), (1, 3),
    (0, 4), (0, 5), (1, 4), (1, 5),
    (2, 4), (2, 5), (3, 4), (3, 5),
]
_BOX_FACE_NORMALS = [
    (0.0, 0.0, -1.0), (0.0, 0.0, 1.0),
    (0.0, -1.0, 0.0), (0.0, 1.0, 0.0),
    (-1.0, 0.0, 0.0), (1.0, 0.0, 0.0),
]


def get_silhouette_edges(
    prim_path: str,
    view_direction: Tuple[float, float, float],
) -> List[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]:
    """카메라 시점에서 prim 바운딩 박스의 실루엣 엣지만 반환합니다."""
    all_edges = get_bbox_edges(prim_path)
    if not all_edges:
        return []

    vx, vy, vz = view_direction
    v_len = (vx * vx + vy * vy + vz * vz) ** 0.5
    if v_len < 1e-8:
        return all_edges
    vx, vy, vz = vx / v_len, vy / v_len, vz / v_len

    result = []
    for i, edge in enumerate(all_edges):
        if i >= len(_EDGE_FACES):
            break
        fa, fb = _EDGE_FACES[i]
        na = _BOX_FACE_NORMALS[fa]
        nb = _BOX_FACE_NORMALS[fb]
        da = na[0] * vx + na[1] * vy + na[2] * vz
        db = nb[0] * vx + nb[1] * vy + nb[2] * vz
        if da * db < 0:
            result.append(edge)
    return result


class _EdgesItem(sc.AbstractManipulatorItem):
    pass


class OutlineModel(sc.AbstractManipulatorModel):
    """Hover 아웃라인용 데이터 모델."""

    def __init__(self):
        super().__init__()
        self._edges: List[Tuple[Tuple[float, float, float], Tuple[float, float, float]]] = []
        self._edges_item = _EdgesItem()

    def get_item(self, identifier):
        if identifier == "edges":
            return self._edges_item
        return super().get_item(identifier)

    def set_edges(self, edges: List[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]):
        self._edges = edges
        self._item_changed(self._edges_item)

    def get_edges(self):
        return self._edges


class HoverOutlineManipulator(sc.Manipulator):
    """Hover된 prim의 실루엣 아웃라인을 sc.Line으로 그리는 Manipulator."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def on_model_updated(self, item):
        self.invalidate()

    def on_build(self):
        if not self.model:
            return
        edges = self.model.get_edges()
        if not edges:
            return

        color = get_outline_color()
        thickness = get_outline_thickness()
        if len(color) < 4:
            color = (1.0, 0.6, 0.0, 1.0)
        line_color = [float(color[0]), float(color[1]), float(color[2]), float(color[3])]

        for start, end in edges:
            ext_start, ext_end = _extend_line(start, end, thickness)
            try:
                sc.Line(list(ext_start), list(ext_end), color=line_color, thickness=thickness)
            except TypeError:
                sc.Line(list(ext_start), list(ext_end), thickness=thickness)
