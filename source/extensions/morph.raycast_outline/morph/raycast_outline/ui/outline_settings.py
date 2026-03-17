# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

"""
Hover 아웃라인 설정 데이터 모듈

색상(RGBA) 및 두께 값을 저장하고 제공합니다.
carb.settings를 사용하지 않으며, 모듈 레벨 변수로 관리합니다.
UI(outline_settings_ui) 및 그리기(actions.outline_draw) 모듈에서 참조합니다.
"""

from typing import Tuple

# -----------------------------------------------------------------------------
# 기본값 상수
# -----------------------------------------------------------------------------
DEFAULT_COLOR: Tuple[float, float, float, float] = (1.0, 0.6, 0.0, 1.0)  # RGBA, 주황색
DEFAULT_THICKNESS: float = 2.0
THICKNESS_MIN: float = 0.5
THICKNESS_MAX: float = 10.0


# -----------------------------------------------------------------------------
# 내부 상태 (모듈 레벨)
# -----------------------------------------------------------------------------
_outline_color: Tuple[float, float, float, float] = DEFAULT_COLOR
_outline_thickness: float = DEFAULT_THICKNESS


# -----------------------------------------------------------------------------
# 공개 API
# -----------------------------------------------------------------------------

def get_outline_color() -> Tuple[float, float, float, float]:
    """
    현재 Hover 아웃라인 색상을 반환합니다.

    Returns:
        (R, G, B, A) 튜플, 각 값 0.0~1.0
    """
    return _outline_color


def set_outline_color(r: float, g: float, b: float, a: float = 1.0) -> None:
    """
    Hover 아웃라인 색상을 설정합니다.

    Args:
        r: Red (0~1)
        g: Green (0~1)
        b: Blue (0~1)
        a: Alpha (0~1), 기본 1.0
    """
    global _outline_color
    _outline_color = (
        max(0, min(1, float(r))),
        max(0, min(1, float(g))),
        max(0, min(1, float(b))),
        max(0, min(1, float(a))),
    )


def get_outline_thickness() -> float:
    """
    현재 Hover 아웃라인 두께를 반환합니다.

    Returns:
        두께 값 (0.5~10.0)
    """
    return _outline_thickness


def set_outline_thickness(value: float) -> None:
    """
    Hover 아웃라인 두께를 설정합니다.

    Args:
        value: 두께 (0.5~10.0 범위로 클램프됨)
    """
    global _outline_thickness
    _outline_thickness = max(THICKNESS_MIN, min(THICKNESS_MAX, float(value)))
