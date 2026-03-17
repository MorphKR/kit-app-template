# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

"""
이벤트에 연결된 동작 모듈

Hover/Click 이벤트 발생 시 수행되는 동작(아웃라인 그리기, overlay 등)을 담당합니다.
"""

from .outline_overlay import OutlineOverlay
from .outline_draw import (
    HoverOutlineManipulator,
    OutlineModel,
    get_silhouette_edges,
    get_bbox_edges,
)

__all__ = [
    "OutlineOverlay",
    "HoverOutlineManipulator",
    "OutlineModel",
    "get_silhouette_edges",
    "get_bbox_edges",
]
